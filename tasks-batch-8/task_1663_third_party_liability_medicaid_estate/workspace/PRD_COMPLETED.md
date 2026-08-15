# Medicaid TPL & Estate Recovery API — Product Requirements Document

## 1. Introduction

State Medicaid programs carry a statutory obligation most beneficiaries never see: when a third party is legally responsible for a member's injuries, Medicaid pays first and pursues the liable party afterward; and when a member dies, the state must seek repayment of correctly paid benefits from the member's estate. This document specifies the Third-Party Liability & Medicaid Estate Recovery API, the system of record for a state Medicaid recovery unit that operates both programs end to end. On the liability side, the unit identifies accident and injury cases, notifies the member's attorney of record, perfects statutory liens within a fixed dollar cap, negotiates settlements whose recovery formula differs by state — subrogation states and reimbursement states compute the state's share differently — tracks pending litigation against the statute of limitations, and accounts for insurer payments net of recovery-contractor commissions. On the estate side, the unit records a member's death, opens an estate case, files a probate claim within the statutory filing window, collects payments against it, and adjudicates hardship waivers that can reduce or extinguish the claim.

Every operation is performed by one of five recovery-unit roles under a segregation-of-duties model that bars decision-makers from acting on records they created themselves. Every time-dependent rule — statute-of-limitations expiry, negotiation freezes, probate filing deadlines, member-notice lateness — is evaluated against a controllable logical clock rather than the wall clock, so that recovery staff and auditors observe identical results. All endpoints are mounted under the `/recovery` path prefix.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting operator and `X-User-Role` to specify their operational capacity. The system recognizes five distinct roles: `SystemAdmin`, `RecoverySpecialist`, `RecoverySupervisor`, `RecoveryAccountant`, and `EstateRecoveryOfficer`. A `SystemAdmin` registers members and operates the logical clock. A `RecoverySpecialist` is the TPL caseworker: identifying cases, recording attorney notification and litigation events, filing and amending liens, negotiating settlements, and sending member notices. A `RecoverySupervisor` accepts and rejects settlements, releases liens, and decides hardship waivers, and is barred by segregation of duties from acting on records they personally created. A `RecoveryAccountant` records insurer checks, posts and reverses recovery postings, records estate payments, and reconciles commission summaries. An `EstateRecoveryOfficer` records member deaths, files probate claims, and files and appeals hardship waivers.

For every one of these five roles — `SystemAdmin`, `RecoverySpecialist`, `RecoverySupervisor`, `RecoveryAccountant`, and `EstateRecoveryOfficer` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow captures an actor (for example, as `created_by_user_id` on a Settlement or a HardshipWaiver, where it feeds the segregation-of-duties check) but does not compare it to any entity's `id`.

A request with a missing or malformed `X-User-ID` or `X-User-Role` header is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400); a blank or whitespace-only `X-User-ID` and a role string outside the five recognized roles both count as malformed. A request whose role is valid but not listed among the endpoint's authorized roles is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100 — a supplied `limit` outside that range is clamped to the nearest bound rather than rejected, and a non-integer `limit` or `offset` falls back to its default. The `offset` parameter specifies the number of items to skip and defaults to 0, with negative values clamped to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order; resources minted at the same timestamp are ordered by creation, earliest first.

List responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. Common Resource Properties

All nine resources — Member, TplCase, ExpenseClaim, Lien, Settlement, RecoveryPosting, EstateCase, HardshipWaiver, and CommunicationNotice — include a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier for the resource, formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments with every modification to the resource.

The mutation rule is total: any change — a client-driven write, a system-driven cascade such as lien satisfaction resolving its case, or recomputation of a derived balance — refreshes `updated_at` and increments `version` on each affected resource. Several workflows in §3 explicitly note the parent whose `version` advances, because two endpoints (§2.7) rely on clients observing those versions.

### 2.5. The Logical Clock and the Statutory Calendar

Time-dependent rules — the statute-of-limitations date, the negotiation freeze, the probate filing deadline, notice lateness — are evaluated against a server-side logical clock, never the wall clock. Before any call to the clock endpoint, the logical clock reads exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time. A `SystemAdmin` may set it by supplying `to_iso8601` — any valid ISO 8601 timestamp is accepted, earlier or later, with no monotonicity check — and the response returns the supplied string verbatim as the new `current_utc`. Expiry and lateness rules are evaluated lazily on subsequent writes rather than by a background sweeper. Timestamps recorded by workflows — `attorney_notified_at`, `filed_at`, `accepted_at`, and `sent_at` — all read this clock, as do every resource's `created_at` and `updated_at` and each response envelope's `api_request_timestamp`.

Statute-of-limitations expiry is lazy. When the logical calendar has advanced past a case's `sol_date`, the next gated write on the case or its lien and settlement children — one of the four operations below that has passed every earlier check in the §2.8 order — moves the case to `SOL_EXPIRED`, moves every lien of the case still in `FILED` or `AMENDED` status to `EXPIRED`, and moves every settlement of the case still in `OFFERED` or `COUNTERED` status to `REJECTED`. Writes not among the four — attorney notification, expense-claim addition, litigation events, case closing, lien filing and release, counters and rejections, posting recording and reversal, and notice sends — never consult the limitations calendar and never fire the cascade. Four operations gate explicitly on the limitations window — opening a settlement negotiation, accepting a settlement, amending a lien, and posting a payment — and each is rejected with `ERR_SOL_EXPIRED` (HTTP 409) at the moment the cascade fires.

### 2.6. Monetary Precision and the Integer-Cent Convention

All monetary values in the system are integer counts of cents; no field stores a fractional cent. Multiplicative results — the attorney fee, the ratio-limited portion of a recovery, the subrogation cost share, and contractor commissions — are rounded half-up to a whole cent. Purely additive and subtractive arithmetic — the lien basis, the estate claim, hardship reductions, outstanding balances — involves no rounding at all; where a subtraction could drive a value negative, an explicit zero floor applies and is stated with the rule.

Contractor commission carries one further ordering rule: each posting's commission is rounded half-up to integer cents at post time, and every period or per-case total is the sum of those per-posting rounded commissions — never a rounding applied to the sum of unrounded values. The two orders disagree on fractional-cent inputs, so the pinned order is part of the contract.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and the guard is non-optional on both.

`POST /recovery/liens/{lienId}/amend` requires the input field `expected_lien_version`, carrying the client's last observed `version` of the lien. If the lien's current `version` has advanced since the client last read it — for example, because another writer has just amended the same lien, and each amendment legitimately supersedes the prior amount — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a lien state it has not observed.

`POST /recovery/cases/{caseId}/settlements` requires the input field `expected_case_version`, carrying the client's last observed `version` of the case. A mismatch with the case's current `version` — for example, because another writer has mutated the case since the client last read it, such as adding an expense claim and thereby changing the lien basis — is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not listed here do not take a version field.

### 2.8. Validation Sequencing

Validation failures are reported against a fixed evaluation order, so the error a client receives is always the earliest applicable check rather than an arbitrary one. The order is:

1. Presence and well-formedness of the `X-User-ID` and `X-User-Role` headers — failure is `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. Role authorization for the endpoint — failure is `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).
3. Request-body shape: required fields present — a string field supplied blank or all-whitespace counts as missing, and calendar-date fields must be valid ISO dates in `YYYY-MM-DD` form — enum values valid, amounts positive where the workflow requires a positive amount, and fee fractions inside their allowed interval — failure is `ERR_INVALID_REQUEST` (HTTP 400).
4. Existence of the resources named in the path, validated left to right — failure is `ERR_NOT_FOUND` (HTTP 404).
5. Segregation of duties, which applies to settlement acceptance and hardship-waiver approval — failure is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
6. State-transition preconditions — failure is `ERR_INVALID_STATE_TRANSITION` (HTTP 409) or one of its specialized variants `ERR_ATTORNEY_NOT_NOTIFIED`, `ERR_LIEN_NOT_AMENDABLE`, `ERR_LIEN_NOT_ACTIVE`, or `ERR_CLAIM_NOT_FILED` (all HTTP 409).
7. Temporal windows on the logical clock — the statute of limitations, the negotiation freeze, and the probate filing deadline — failure is `ERR_SOL_EXPIRED`, `ERR_NEGOTIATION_FREEZE`, or `ERR_ESTATE_FILING_LATE` (all HTTP 409).
8. Uniqueness and aggregate constraints — failure is `ERR_DUPLICATE_EPISODE_CASE`, `ERR_LIEN_ALREADY_EXISTS`, `ERR_NEGOTIATION_IN_PROGRESS`, `ERR_ESTATE_CASE_EXISTS`, `ERR_WAIVER_PENDING_EXISTS`, or `ERR_APPEAL_LIMIT_REACHED` (all HTTP 409).
9. Fiscal rules — failure is `ERR_LIEN_EXCEEDS_CAP`, `ERR_HARDSHIP_CRITERIA_NOT_MET`, `ERR_PAYMENT_EXCEEDS_OUTSTANDING`, or `ERR_POSTING_EXCEEDS_RECOVERY` (all HTTP 409).

On the two OCC-guarded writes of §2.7, the stale-version check runs last, after all business checks above. A request therefore surfaces an expired limitations date before a uniqueness conflict, and never reports a stale version for a request that already fails an earlier rule.

### 2.9. Cascading Reconciliation Across the Recovery Ledger

Status changes propagate across entity boundaries without a separate client request on the affected resource. Posting a payment can satisfy a lien, resolve the lien's case, and disburse the case's settlement in a single atomic step; reversing that payment unwinds each of those states. Approving a full hardship waiver moves its estate case to `WAIVED`; rescinding the waiver restores the claim. Derived balances — the case's `total_paid_claims_cents` and `total_recovered_cents`, the lien's `outstanding_cents`, the estate's `claim_outstanding_cents` — are recomputed from their underlying records on every contributing mutation, so the values a client reads always reflect the complete claim, posting, payment, and waiver history. Each such reconciliation mutates the affected resource, refreshing its `updated_at` and incrementing its `version` per §2.4.

### 2.10. Nested Resource Retrieval

Endpoints whose paths name a parent resource and a child resource — for example filing a lien beneath `/recovery/cases/{caseId}/liens`, or recording a payment beneath `/recovery/estate-cases/{estateCaseId}/record-payment` — validate path identifiers in a strict left-to-right order. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not name an existing resource, and no later check runs: a request naming a nonexistent case never reaches the lien or settlement rules, and a request naming a nonexistent estate case never reaches the payment rules.

### 2.11. Member Communication Obligations

Five business events generate a CommunicationNotice to the member: lien filing, settlement acceptance, case resolution, estate claim filing, and every hardship-waiver decision. Each notice is created in `QUEUED` status, and its `due_date` is the creation calendar date plus thirty days — the member-communication deadline. A notice always carries `member_id`; its `case_id` is set for the three TPL notice types and null for estate notices, while its `estate_case_id` is set for the two estate notice types and null for TPL notices. Delivery is attempted by a `RecoverySpecialist`; each attempt records `sent_at` from the logical clock and computes `is_late`, which is true when the sent calendar date falls after the `due_date`. Until the first attempt, both `sent_at` and `is_late` are null.

## 3. Business Logic & Workflows

### 3.1. Enrolling Members and Determining the Recovery Approach

A `SystemAdmin` registers each Medicaid beneficiary as a Member by supplying the member's `medicaid_id` — the state Medicaid beneficiary identifier, recorded exactly as supplied with no server-enforced uniqueness check — together with the member's legal `full_name` and the `state_code` of the member's Medicaid program, likewise recorded exactly as supplied with no format validation. New members begin in `ACTIVE` status; the only other member status is `DECEASED`, which is terminal.

The `state_code` does more than label the program: the server derives the member's `recovery_approach` from it, and that derivation selects which settlement recovery formula the member's cases will use. Members whose `state_code` is exactly `MT` or `WY` — the match is case-sensitive — are assigned `SUBROGATION`; every other `state_code` is assigned `REIMBURSEMENT`. While a member is living, their `date_of_death` is null; §3.6 describes how it is set.

### 3.2. Case Identification, Attorney Notification, and the Litigation Track

When Medicaid has paid for treatment of an injury a third party may be liable for, a `RecoverySpecialist` identifies a TplCase with a payload naming the injured beneficiary via `member_id`, the member's injury-claim attorney of record via `attorney_name` and `attorney_email` (the contact address later used for attorney notification), the `injury_date` of the accident, and the `third_party_insurer` believed liable. A `member_id` that names no registered member is rejected with `ERR_NOT_FOUND` (HTTP 404). The case is created in `IDENTIFIED` status with its litigation track at `NO_SUIT`, and the server computes `sol_date` as the same calendar date three years after the `injury_date` (a February 29 injury yields a February 28 limitations date) — the statute-of-limitations date that governs every later deadline on the case.

One member cannot carry two overlapping injury episodes. If the same member already has a non-terminal case — one not yet `RESOLVED`, `CLOSED_NO_RECOVERY`, or `SOL_EXPIRED` — and the new case's `injury_date` falls on or after the existing case's `injury_date` and before the calendar date ninety days after it, the identification is rejected with `ERR_DUPLICATE_EPISODE_CASE` (HTTP 409). The window is half-open: an `injury_date` exactly ninety days after the existing case's injury date is permitted.

Attorney notification is a distinct, recorded step. A `RecoverySpecialist` records it against a case in `IDENTIFIED` status, moving the case to `ATTORNEY_NOTIFIED`, stamping `attorney_notified_at` — null until this step is taken — with the current logical clock, and incrementing the case's `version`. Attempting it from any other status is a generic state error, `ERR_INVALID_STATE_TRANSITION` (HTTP 409).

Medicaid's paid medical claims accumulate on the case as ExpenseClaim records. A `RecoverySpecialist` adds each claim with its `service_date`, the `paid_amount_cents` Medicaid paid (which must be greater than zero), and the external `claim_reference` from the MMIS feed. The server derives `included_in_lien_basis` for each claim: true exactly when the claim's `service_date` falls on or after the case's `injury_date`, compared as calendar dates; claims dated before the injury never feed the lien. The case's `total_paid_claims_cents` is then recomputed as the sum of `paid_amount_cents` over all of the case's expense claims — included in the lien basis or not — and each addition increments the case's `version`, which is why a client holding a stale case version cannot open a negotiation afterward (§2.7). Adding a claim is not gated on the case's status — it succeeds even on a terminal case — and never fires the §2.5 expiry cascade. Caseworkers can retrieve a case's claims as a list, and can list cases themselves filtered by `member_id` or `status`.

Litigation proceeds on a parallel dimension, `litigation_status`, which evolves independently of the resolution-track `status`. A `RecoverySpecialist` records a litigation event by supplying `litigation_event`: `FILE_SUIT` moves `NO_SUIT` to `SUIT_FILED`; `RECORD_JUDGMENT` moves `SUIT_FILED` to `JUDGMENT`; `RECORD_DISMISSAL` moves `SUIT_FILED` to `SUIT_DISMISSED`; and a further `FILE_SUIT` after dismissal refills the track, moving `SUIT_DISMISSED` back to `SUIT_FILED`. Filing suit — whether the initial filing or a refiling after dismissal — is accepted only while the case's resolution track is non-terminal, that is, not `RESOLVED`, `CLOSED_NO_RECOVERY`, or `SOL_EXPIRED`; otherwise the event is rejected with `ERR_INVALID_STATE_TRANSITION`. Every accepted litigation event increments the case's `version`. A `litigation_event` value outside the three enumerations is a body-shape failure, `ERR_INVALID_REQUEST`.

Not every case proceeds. While a case stands at `IDENTIFIED` or `ATTORNEY_NOTIFIED`, a `RecoverySpecialist` or `RecoverySupervisor` may close it with no recovery, moving it to the terminal `CLOSED_NO_RECOVERY` status and incrementing the case's `version`; from `LIEN_FILED` onward the close is a generic state error. The case's terminal states are `RESOLVED`, `CLOSED_NO_RECOVERY`, and `SOL_EXPIRED`; the lazy expiry of §2.5 delivers the last of these.

### 3.3. Perfecting and Managing the Statutory Lien

With the attorney notified, a `RecoverySpecialist` files the statutory lien against the case. The case must stand at `ATTORNEY_NOTIFIED`: filing while the case is still `IDENTIFIED` — attorney notification not yet recorded — is rejected with `ERR_ATTORNEY_NOT_NOTIFIED` (HTTP 409), while filing from any later or terminal status is a generic state error — save that the uniqueness check fires first: only one active lien may exist per case, and a filing against a case that already has a lien in `FILED` or `AMENDED` status is rejected with `ERR_LIEN_ALREADY_EXISTS` (HTTP 409) whatever the case's status.

Filing perfects the lien amount from the case's claims. The lien basis is the sum of `paid_amount_cents` over the case's expense claims whose `included_in_lien_basis` is true — that is, claims dated on or after the injury. The recorded `lien_amount_cents` is the lesser of that basis and the statutory lien cap of 250,000 cents (two thousand five hundred dollars). The cap itself is preserved on the lien as `statutory_cap_cents`, a snapshot taken at filing time so that later statutory changes cannot retroactively alter what this lien may hold; `filed_at` records the logical-clock timestamp of filing. The new lien stands at `FILED` status — its full lifecycle spans `FILED`, `AMENDED`, `SATISFIED`, `RELEASED`, and `EXPIRED`, the last three being terminal — with `amended_count` at zero and `outstanding_cents` equal to `lien_amount_cents` less any posted recoveries (none can exist yet). Filing moves the case from `ATTORNEY_NOTIFIED` to `LIEN_FILED` and queues a `LIEN_FILED_NOTICE` to the member per §2.11. Liens can be listed filtered by `case_id` or `status`.

Lien amounts are amended as new claims arrive. A `RecoverySpecialist` amends a lien by supplying `new_amount_cents` — an integer, zero or greater — together with the OCC guard `expected_lien_version` (§2.7). Amendment is defined from `FILED` to `AMENDED` and again from `AMENDED` to `AMENDED`; attempting it on a lien in `SATISFIED`, `RELEASED`, or `EXPIRED` status is rejected with `ERR_LIEN_NOT_AMENDABLE` (HTTP 409). Three business gates then apply, in the validation order of §2.8. First, the negotiation freeze: for every settlement on the case in `OFFERED` or `COUNTERED` status, the current logical timestamp must be strictly later than fourteen days after that settlement's `updated_at`; the interval is closed, so a lien whose open negotiation was updated exactly fourteen days ago remains frozen, and a blocked amendment is rejected with `ERR_NEGOTIATION_FREEZE` (HTTP 409). Second, the statute of limitations: amendment on or before the case's `sol_date` proceeds; after it, the lazy expiry cascade of §2.5 fires and the amendment is rejected with `ERR_SOL_EXPIRED`. Third, the cap: `new_amount_cents` must not exceed the lien's `statutory_cap_cents` snapshot, or the amendment is rejected with `ERR_LIEN_EXCEEDS_CAP` (HTTP 409). Finally the stale-version guard runs. A successful amendment replaces `lien_amount_cents` with `new_amount_cents`, recomputes `outstanding_cents`, increments `amended_count` by one, and increments the lien's `version` by one.

A `RecoverySupervisor` may release a lien in `FILED` or `AMENDED` status, moving it to `RELEASED` — but only while no RecoveryPosting in `POSTED` status exists on the lien; releasing against posted money is a generic state error. Release feeds back into the case: when the case stands at `LIEN_FILED`, it reverts to `ATTORNEY_NOTIFIED`; when the case stands at `SETTLEMENT_PENDING`, its status is left unchanged.

### 3.4. Settlement Negotiation, Acceptance, and the Recovery Formula

Once a lien stands filed, a `RecoverySpecialist` or `RecoverySupervisor` opens settlement negotiation on the case. The payload carries the four offer fields — `gross_amount_cents` (the gross third-party settlement amount, which must be greater than zero), `attorney_fee_pct` (the contingency fee fraction, strictly greater than zero and strictly less than one), `litigation_costs_cents` (costs off the top, zero or greater), and `offered_by` (either `INSURER` or `STATE`, naming which side tabled the offer) — plus the OCC guard `expected_case_version` (§2.7). Negotiation may open whenever a lien in `FILED` or `AMENDED` status stands behind the case — the case's own status is not consulted, so a case still at `SETTLEMENT_PENDING` after an acceptance can open a fresh negotiation; absent an active lien the attempt is rejected with `ERR_INVALID_STATE_TRANSITION`. Only one negotiation may be live at a time: if a settlement in `OFFERED` or `COUNTERED` status already exists on the case, the attempt is rejected with `ERR_NEGOTIATION_IN_PROGRESS` (HTTP 409). The statute-of-limitations gate of §2.5 applies, and the stale-version guard runs last, per the ordering of §2.8. Malformed payloads — a missing field, an `offered_by` outside the enumeration, a non-positive gross, a fee fraction outside its open interval — fail earlier still with `ERR_INVALID_REQUEST`.

A successful opening creates the Settlement in `OFFERED` status with `round_number` 1, records the creator's `X-User-ID` as `created_by_user_id` for the later segregation-of-duties check, leaves `accepted_at` null, and moves the case from `LIEN_FILED` to `SETTLEMENT_PENDING`, incrementing the case's `version` by one. The settlement's lifecycle spans `OFFERED`, `COUNTERED`, `ACCEPTED`, `REJECTED`, and `DISBURSED`, with `REJECTED` and `DISBURSED` terminal. Settlements can be listed filtered by `case_id` or `status`.

Four amounts are derived on the settlement, at creation and again on every counter — and, for the recovery amount, once more at acceptance. The attorney fee `fee_amount_cents` is the `gross_amount_cents` multiplied by `attorney_fee_pct`, rounded half-up to a whole cent, in both variants. Which formula produces `state_recovery_cents` depends on the member's `recovery_approach` (§3.1):

- Under `REIMBURSEMENT`, the state recovers the smallest of three values — the lien's current `outstanding_cents`; the gross less the attorney fee and less the litigation costs; and thirty-five percent of the gross amount, that statutory medical portion rounded half-up to a whole cent — floored at zero so the recovery is never negative. The `cost_share_cents` is zero under this variant.
- Under `SUBROGATION`, the state stands in the member's shoes and evaluation order is pinned. First, the pre-cost recovery is the lesser of the lien's current `outstanding_cents` and the `gross_amount_cents`. Second, `cost_share_cents` is the lesser of `litigation_costs_cents` and twenty-five percent of that pre-cost recovery, the percentage rounded half-up to a whole cent — the cap is always a fraction of the pre-cost recovery, never of the post-deduction value. Third, `state_recovery_cents` is the pre-cost recovery minus `cost_share_cents`.

Under both variants, the member's `member_net_cents` is the `gross_amount_cents` less `fee_amount_cents`, less `litigation_costs_cents`, less `state_recovery_cents`.

Negotiation then alternates. A counter by a `RecoverySpecialist` or `RecoverySupervisor` moves `OFFERED` to `COUNTERED`, and the next counter moves `COUNTERED` back to `OFFERED`; each counter increments `round_number` by one, replaces all four offer fields — `gross_amount_cents`, `attorney_fee_pct`, `litigation_costs_cents`, and `offered_by` — from the payload, and recomputes `fee_amount_cents`, `cost_share_cents`, `state_recovery_cents`, and `member_net_cents` under the same formulas (countering does not require an active lien; when none exists, the lien outstanding feeding the formulas is zero). Countering is possible only from `OFFERED` or `COUNTERED`; from any other status it is a generic state error.

Acceptance is reserved for a `RecoverySupervisor` and carries three gates, applied in the §2.8 order. Segregation of duties comes first: the acting `X-User-ID` must differ from the settlement's `created_by_user_id`, and a supervisor accepting their own offer is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The settlement must stand at `OFFERED` or `COUNTERED`, and a lien in `FILED` or `AMENDED` status must exist on the case; without an active lien the acceptance is rejected with `ERR_LIEN_NOT_ACTIVE` (HTTP 409). The statute-of-limitations gate then applies as in §2.5. On acceptance the recovery is recomputed against the lien's current `outstanding_cents` — derived-field reconciliation, since amendments or postings may have moved the outstanding balance since the offer was tabled — and `fee_amount_cents`, `cost_share_cents`, and `member_net_cents` are recomputed with it. The settlement moves from `OFFERED` or `COUNTERED` to `ACCEPTED`, `accepted_at` is stamped from the logical clock, and a `SETTLEMENT_NOTICE` is queued to the member per §2.11.

Rejection is likewise a `RecoverySupervisor` decision, available from `OFFERED` or `COUNTERED`: the settlement moves to the terminal `REJECTED` status, and the case falls back from `SETTLEMENT_PENDING` to `LIEN_FILED`, freeing the lien for a later negotiation. The lazy expiry of §2.5 can also reject a settlement without any supervisor action, moving `OFFERED` or `COUNTERED` to `REJECTED` as the case itself goes `SOL_EXPIRED`.

### 3.5. Insurer Payments, Contractor Commission, and Disbursement

When the insurer's check arrives, a `RecoveryAccountant` records a RecoveryPosting against an `ACCEPTED` settlement, supplying the `gross_recovery_cents` received (which must be greater than zero) and the `contractor_code` identifying the recovery contractor for commission attribution. Installments are allowed: several postings may accumulate against one settlement, but the cumulative `gross_recovery_cents` of non-`REVERSED` postings on a settlement must never exceed that settlement's `state_recovery_cents`; a recording that would cross the line is rejected with `ERR_POSTING_EXCEEDS_RECOVERY` (HTTP 409). Recording is defined only against a settlement in `ACCEPTED` status; against a settlement in any other status it is rejected as an invalid state, `ERR_INVALID_STATE_TRANSITION`. The posting is created in `PENDING` status — its lifecycle spans `PENDING`, `POSTED`, and `REVERSED`, with `REVERSED` terminal — carrying `settlement_id` of the accepted settlement and a `lien_id` snapshot of the case's active lien at creation (null when no active lien exists at that moment), with `commission_cents` and `net_to_state_cents` both null while the posting remains unposted. Postings can be listed filtered by `settlement_id`, `lien_id`, or `status`.

Posting the payment is the accountant's confirmation that funds cleared. A posting in `PENDING` moves to `POSTED`, provided the current calendar date is on or before the `sol_date` of the posting's settlement's case; past that date the lazy expiry cascade of §2.5 fires and the post is rejected with `ERR_SOL_EXPIRED`. Posting computes the contractor's commission on the check, in tiers: ten percent of the portion of `gross_recovery_cents` up to and including 100,000 cents (one thousand dollars); seven and a half percent of the portion above 100,000 cents, up to a further 100,000 cents of width; and five percent of any portion above 200,000 cents. The three tier products are summed and the result is rounded half-up once — at post time, per posting, per the ordering rule of §2.6 — yielding `commission_cents`; `net_to_state_cents` is then the `gross_recovery_cents` less `commission_cents`. The lien's `outstanding_cents` is reduced by the `gross_recovery_cents`. When that reduction drives the lien's outstanding balance to exactly zero, the lien — whether `FILED` or `AMENDED` — becomes `SATISFIED`; a case standing at `SETTLEMENT_PENDING` is in turn resolved, moving to `RESOLVED` with its `total_recovered_cents` recomputed as the sum of `gross_recovery_cents` over the case's `POSTED` postings, and a `CASE_RESOLUTION_NOTICE` is queued to the member per §2.11. The first posting to reach `POSTED` on a settlement also moves that settlement from `ACCEPTED` to `DISBURSED`. Note that `RESOLVED` is reachable only through lien satisfaction; there is no direct resolve action on a case.

Reversal is the compensating action, available to a `RecoveryAccountant` while the posting stands at `POSTED`. Reversing moves the posting to `REVERSED` and unwinds its effects: the lien's `outstanding_cents` is increased by the `gross_recovery_cents`, excluding the posting from the posted set; if the lien had been `SATISFIED`, it reverts to `FILED`, and a case that had been `RESOLVED` reverts to `SETTLEMENT_PENDING`; if no `POSTED` postings remain on the settlement, the settlement falls back from `DISBURSED` to `ACCEPTED`; and the case's `total_recovered_cents` is recomputed without the reversed posting.

For reconciliation, an accounting summary read on a case reports `total_recovered_cents` (the sum of `gross_recovery_cents` over the case's `POSTED` postings), `total_commission_cents` (the sum of `commission_cents` over those same postings), `total_net_to_state_cents` (the first total less the second), and `posting_count` (the number of `POSTED` postings contributing). `PENDING` and `REVERSED` postings are excluded from every figure. This summary is available to `RecoveryAccountant`, `RecoverySupervisor`, and `SystemAdmin`.

### 3.6. Estate Recovery: Death Recording and the Probate Claim

Estate recovery begins when an `EstateRecoveryOfficer` records a member's death, supplying the `date_of_death` and the `lifetime_paid_cents` snapshot of total Medicaid payments reported by the MMIS feed (an integer, zero or greater). The member must not already have an estate case; a second recording is rejected with `ERR_ESTATE_CASE_EXISTS` (HTTP 409). The member moves from `ACTIVE` to `DECEASED`, both supplied values are recorded on the member, and the member's `version` increments by one; the response returns the updated Member with 200 OK, and the EstateCase opened by the same action is read through the estate-case endpoints.

The same action opens the EstateCase in `OPENED` status — its lifecycle spans `OPENED`, `CLAIM_FILED`, `PAID`, `WAIVED`, and `TIME_BARRED`, the last three terminal — carrying the decedent's `member_id`, a `date_of_death` copied from the member, and the `lifetime_paid_cents` snapshot. At opening the claim is provisional: `provisional_claim_cents` equals the `lifetime_paid_cents` in full, with no offsets — a conservative upper bound used for the probate notice. The final `claim_amount_cents` remains null until the claim is filed, `claim_outstanding_cents` is zero while the case is `OPENED`, `total_paid_cents` starts at zero, and `probate_case_number` and `exempt_services_cents` are null until captured at filing. Estate cases can be listed filtered by `member_id` or `status`.

Filing the probate claim is the `EstateRecoveryOfficer`'s next step, permitted only from `OPENED`; from any other status it is a generic state error, `ERR_INVALID_STATE_TRANSITION` (HTTP 409). The statute allows three hundred sixty-five days: the current calendar date must be on or before the date three hundred sixty-five days after the `date_of_death`. A filing attempted later moves the estate case from `OPENED` to `TIME_BARRED` and is rejected with `ERR_ESTATE_FILING_LATE` (HTTP 409). A timely filing records the `probate_case_number` and the statutorily exempt `exempt_services_cents` (an integer, zero or greater) from the payload, then fixes the final claim. First, the TPL offset is computed as the sum of `gross_recovery_cents` over all `POSTED` recovery postings whose settlement belongs to a TPL case of this member — dollars the program has already recovered from liable third parties. Second, `claim_amount_cents` is the `lifetime_paid_cents` less that TPL offset and less `exempt_services_cents`, floored at zero. The `claim_outstanding_cents` is set equal to the `claim_amount_cents`, an `ESTATE_CLAIM_NOTICE` is queued to the member's estate per §2.11, and the case moves to `CLAIM_FILED`. Should the final claim compute to exactly zero, there is nothing to collect: the case passes immediately from `CLAIM_FILED` to `PAID`.

Against a filed claim, a `RecoveryAccountant` records estate payments. The estate case must stand at `CLAIM_FILED`; a payment — or a waiver application, §3.7 — attempted on an estate case in any other status is rejected with `ERR_CLAIM_NOT_FILED` (HTTP 409). Each payment carries `amount_cents`, which must be greater than zero and must not exceed the current `claim_outstanding_cents`; an overpayment is rejected with `ERR_PAYMENT_EXCEEDS_OUTSTANDING` (HTTP 409). A recorded payment raises `total_paid_cents` by `amount_cents` and lowers `claim_outstanding_cents` by the same amount. The outstanding balance is always derived the same way: `claim_amount_cents` less `total_paid_cents` less the sum of `decided_reduction_cents` over approved waivers that have not been rescinded. When a payment — or, per §3.7, a waiver approval — drives the outstanding balance to exactly zero, the case moves automatically from `CLAIM_FILED` to `PAID`.

### 3.7. Hardship Waivers: Decision, Appeal, and Rescission

Heirs facing an estate claim may seek hardship relief. An `EstateRecoveryOfficer` or `RecoverySupervisor` applies for a HardshipWaiver on an estate case in `CLAIM_FILED` status (otherwise `ERR_CLAIM_NOT_FILED`), and only one waiver may be pending at a time: if a waiver in `PENDING` status already exists on the estate case, the application is rejected with `ERR_WAIVER_PENDING_EXISTS` (HTTP 409). The application supplies the `waiver_type` — `FULL` or `PARTIAL` — plus the heir household's `household_income_annual_cents` and the `homestead_value_cents`, both of which must be zero or greater. The `requested_reduction_cents` is required exactly when the `waiver_type` is `PARTIAL`, must be greater than zero when present, and is ignored for a `FULL` application — a value supplied with one is recorded on the waiver but plays no role in the decision. The waiver is created in `PENDING` status — its lifecycle spans `PENDING`, `APPROVED`, `DENIED`, and `RESCINDED` — with the filer's `X-User-ID` recorded as `created_by_user_id`, `appeal_count` at zero, and `decided_reduction_cents` null. Waivers can be listed filtered by `estate_case_id` or `status`.

Approval is a `RecoverySupervisor` decision on a `PENDING` waiver, gated first by segregation of duties: the acting `X-User-ID` must differ from the waiver's `created_by_user_id`, or the approval is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A `FULL` waiver additionally must satisfy the statutory hardship criteria: the `homestead_value_cents` must be at most 5,000,000 cents (fifty thousand dollars) and the `household_income_annual_cents` must be at most 3,000,000 cents (thirty thousand dollars); failing either prong rejects the approval with `ERR_HARDSHIP_CRITERIA_NOT_MET` (HTTP 409). The decided reduction then depends on the type. For a `FULL` waiver, `decided_reduction_cents` is the estate case's entire `claim_outstanding_cents` at the moment of approval. For a `PARTIAL` waiver, the computation runs in order: the exposed equity is the `homestead_value_cents` less the fifty-thousand-dollar homestead exemption, floored at zero; the collectible amount is the estate's `claim_outstanding_cents` less that exposed equity, again floored at zero; and `decided_reduction_cents` is the lesser of `requested_reduction_cents` and the collectible amount. Approval subtracts the decided reduction from the estate's `claim_outstanding_cents`. A `FULL` approval zeroes the balance and moves the estate case from `CLAIM_FILED` to `WAIVED`; a `PARTIAL` approval leaves the estate case in `CLAIM_FILED` unless the reduction happens to drive the outstanding balance to exactly zero, in which case the case moves to `PAID`. Either way an `ESTATE_DECISION_NOTICE` is queued per §2.11.

Denial is the other `RecoverySupervisor` decision on a `PENDING` waiver: the waiver moves to `DENIED` and an `ESTATE_DECISION_NOTICE` is queued; `decided_reduction_cents` remains null, since nothing was granted. `DENIED` is not final. An `EstateRecoveryOfficer` may appeal a denied waiver once, moving it from `DENIED` back to `PENDING` and incrementing `appeal_count` by one; when `appeal_count` has already reached one, a further appeal is rejected with `ERR_APPEAL_LIMIT_REACHED` (HTTP 409). Of the four waiver statuses, `APPROVED` and `RESCINDED` are terminal; `DENIED` remains open to that single appeal.

Rescission unwinds a grant. A `RecoverySupervisor` may rescind an `APPROVED` waiver, moving it to `RESCINDED`: the estate case's `claim_outstanding_cents` is increased by the waiver's `decided_reduction_cents`, and an estate case that had been `WAIVED` returns to `CLAIM_FILED` with its outstanding balance restored to the `claim_amount_cents` less `total_paid_cents` less whatever approved reductions from other waivers remain. An estate case the approval had instead driven to `PAID` likewise regains the balance but remains `PAID`.

### 3.8. Member Communications and Delivery Deadlines

Every notice the workflows create — `LIEN_FILED_NOTICE` at lien filing, `SETTLEMENT_NOTICE` at settlement acceptance, `CASE_RESOLUTION_NOTICE` at case resolution, `ESTATE_CLAIM_NOTICE` at probate claim filing, and `ESTATE_DECISION_NOTICE` at each waiver approval or denial — arrives in `QUEUED` status with the thirty-day `due_date` of §2.11. The three TPL notice types carry the case's `case_id` and a null `estate_case_id`; the two estate notice types carry the estate's `estate_case_id` and a null `case_id`; all five carry the recipient's `member_id`. A notice's lifecycle spans `QUEUED`, `DELIVERED`, and `FAILED`, with `DELIVERED` terminal. Notices can be listed filtered by `member_id`, `case_id`, `estate_case_id`, `notice_type`, or `status`.

A `RecoverySpecialist` sends or retries a notice by supplying `delivery_outcome`, either `DELIVERED` or `FAILED` — any other value is a body-shape failure, `ERR_INVALID_REQUEST`. From `QUEUED`, a `DELIVERED` outcome moves the notice to `DELIVERED` and a `FAILED` outcome moves it to `FAILED`; from `FAILED`, a retry with `DELIVERED` completes delivery while a retry with `FAILED` leaves the notice in `FAILED`. Each attempt stamps `sent_at` from the logical clock and recomputes `is_late` as true exactly when the sent calendar date falls after the `due_date`, so a retry updates both fields to reflect the latest attempt. Sending a notice that is already `DELIVERED` is a generic state error, `ERR_INVALID_STATE_TRANSITION`.

## 4. Endpoint Definitions

Operations that create a new resource — registering a member, identifying a case, adding an expense claim, filing a lien, opening a negotiation, recording a check, applying for a waiver — return `201 Created`. Operations that modify an existing resource or drive a state transition return `200 OK`. Request payloads, derived fields, side effects, and error conditions for each operation are specified in §2 and §3; this table is a locator, not a restatement.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/recovery/members` | Register a Medicaid member | SystemAdmin |
| GET | `/recovery/members/{memberId}` | Get a member | SystemAdmin, RecoverySpecialist, RecoverySupervisor, RecoveryAccountant, EstateRecoveryOfficer |
| POST | `/recovery/members/{memberId}/mark-deceased` | Record member death; opens the estate recovery case | EstateRecoveryOfficer |
| POST | `/recovery/cases` | Identify a third-party liability accident/injury case | RecoverySpecialist |
| GET | `/recovery/cases/{caseId}` | Get a TPL case | SystemAdmin, RecoverySpecialist, RecoverySupervisor, RecoveryAccountant, EstateRecoveryOfficer |
| GET | `/recovery/cases` | List TPL cases with filters | SystemAdmin, RecoverySpecialist, RecoverySupervisor, RecoveryAccountant, EstateRecoveryOfficer |
| POST | `/recovery/cases/{caseId}/notify-attorney` | Record attorney notification | RecoverySpecialist |
| POST | `/recovery/cases/{caseId}/expense-claims` | Add a Medicaid paid claim to the injury case | RecoverySpecialist |
| GET | `/recovery/cases/{id}/expense-claims` | List expense claims of a case | SystemAdmin, RecoverySpecialist, RecoverySupervisor, RecoveryAccountant, EstateRecoveryOfficer |
| POST | `/recovery/cases/{caseId}/litigation` | Record a litigation-track event on the case | RecoverySpecialist |
| POST | `/recovery/cases/{caseId}/close` | Close a case with no recovery | RecoverySpecialist, RecoverySupervisor |
| GET | `/recovery/cases/{caseId}/accounting-summary` | Recovery accounting totals for the case | RecoveryAccountant, RecoverySupervisor, SystemAdmin |
| POST | `/recovery/cases/{caseId}/liens` | File the statutory lien | RecoverySpecialist |
| GET | `/recovery/liens/{lienId}` | Get a lien | SystemAdmin, RecoverySpecialist, RecoverySupervisor, RecoveryAccountant, EstateRecoveryOfficer |
| GET | `/recovery/liens` | List liens with filters | SystemAdmin, RecoverySpecialist, RecoverySupervisor, RecoveryAccountant, EstateRecoveryOfficer |
| POST | `/recovery/liens/{lienId}/amend` | Amend the lien amount (OCC-guarded; blocked during negotiation freeze) | RecoverySpecialist |
| POST | `/recovery/liens/{lienId}/release` | Release the lien | RecoverySupervisor |
| POST | `/recovery/cases/{caseId}/settlements` | Open settlement negotiation (OCC on case version) | RecoverySpecialist, RecoverySupervisor |
| GET | `/recovery/settlements/{settlementId}` | Get a settlement | SystemAdmin, RecoverySpecialist, RecoverySupervisor, RecoveryAccountant, EstateRecoveryOfficer |
| GET | `/recovery/settlements` | List settlements with filters | SystemAdmin, RecoverySpecialist, RecoverySupervisor, RecoveryAccountant, EstateRecoveryOfficer |
| POST | `/recovery/settlements/{settlementId}/counter` | Counter-offer: advances the negotiation round | RecoverySpecialist, RecoverySupervisor |
| POST | `/recovery/settlements/{settlementId}/accept` | Accept the settlement (segregation of duties vs creator) | RecoverySupervisor |
| POST | `/recovery/settlements/{settlementId}/reject` | Reject the settlement; case returns to lien-filed | RecoverySupervisor |
| POST | `/recovery/settlements/{settlementId}/postings` | Record an insurer check against an accepted settlement | RecoveryAccountant |
| GET | `/recovery/postings/{postingId}` | Get a recovery posting | SystemAdmin, RecoverySpecialist, RecoverySupervisor, RecoveryAccountant, EstateRecoveryOfficer |
| GET | `/recovery/postings` | List recovery postings with filters | SystemAdmin, RecoverySpecialist, RecoverySupervisor, RecoveryAccountant, EstateRecoveryOfficer |
| POST | `/recovery/postings/{postingId}/post` | Post the payment: computes commission, applies to lien, cascades satisfaction | RecoveryAccountant |
| POST | `/recovery/postings/{postingId}/reverse` | Reverse a posted payment (compensating action) | RecoveryAccountant |
| GET | `/recovery/estate-cases/{estateCaseId}` | Get an estate case | SystemAdmin, RecoverySpecialist, RecoverySupervisor, RecoveryAccountant, EstateRecoveryOfficer |
| GET | `/recovery/estate-cases` | List estate cases with filters | SystemAdmin, RecoverySpecialist, RecoverySupervisor, RecoveryAccountant, EstateRecoveryOfficer |
| POST | `/recovery/estate-cases/{estateCaseId}/file-claim` | File the probate estate claim (365-day filing deadline) | EstateRecoveryOfficer |
| POST | `/recovery/estate-cases/{estateCaseId}/record-payment` | Record an estate payment against the outstanding claim | RecoveryAccountant |
| POST | `/recovery/estate-cases/{estateCaseId}/waivers` | Apply for a hardship waiver on the estate claim | EstateRecoveryOfficer, RecoverySupervisor |
| GET | `/recovery/waivers/{waiverId}` | Get a hardship waiver | SystemAdmin, RecoverySpecialist, RecoverySupervisor, RecoveryAccountant, EstateRecoveryOfficer |
| GET | `/recovery/waivers` | List hardship waivers with filters | SystemAdmin, RecoverySpecialist, RecoverySupervisor, RecoveryAccountant, EstateRecoveryOfficer |
| POST | `/recovery/waivers/{waiverId}/approve` | Approve a hardship waiver (segregation of duties vs filer) | RecoverySupervisor |
| POST | `/recovery/waivers/{waiverId}/deny` | Deny a hardship waiver | RecoverySupervisor |
| POST | `/recovery/waivers/{waiverId}/appeal` | Appeal a denied waiver (one appeal maximum) | EstateRecoveryOfficer |
| POST | `/recovery/waivers/{waiverId}/rescind` | Rescind an approved waiver, restoring the estate claim | RecoverySupervisor |
| GET | `/recovery/notices/{noticeId}` | Get a member communication notice | SystemAdmin, RecoverySpecialist, RecoverySupervisor, RecoveryAccountant, EstateRecoveryOfficer |
| GET | `/recovery/notices` | List member communication notices with filters | SystemAdmin, RecoverySpecialist, RecoverySupervisor, RecoveryAccountant, EstateRecoveryOfficer |
| POST | `/recovery/notices/{noticeId}/send` | Send or retry a queued/failed notice; records lateness | RecoverySpecialist |
| POST | `/recovery/_clock/set_current_utc` | Set the server logical clock (test-driving endpoint) | SystemAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3 alongside the workflow that raises it.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_ATTORNEY_NOT_NOTIFIED` | 409 Conflict |
| `ERR_LIEN_NOT_AMENDABLE` | 409 Conflict |
| `ERR_LIEN_NOT_ACTIVE` | 409 Conflict |
| `ERR_CLAIM_NOT_FILED` | 409 Conflict |
| `ERR_SOL_EXPIRED` | 409 Conflict |
| `ERR_NEGOTIATION_FREEZE` | 409 Conflict |
| `ERR_ESTATE_FILING_LATE` | 409 Conflict |
| `ERR_DUPLICATE_EPISODE_CASE` | 409 Conflict |
| `ERR_LIEN_ALREADY_EXISTS` | 409 Conflict |
| `ERR_NEGOTIATION_IN_PROGRESS` | 409 Conflict |
| `ERR_ESTATE_CASE_EXISTS` | 409 Conflict |
| `ERR_WAIVER_PENDING_EXISTS` | 409 Conflict |
| `ERR_APPEAL_LIMIT_REACHED` | 409 Conflict |
| `ERR_HARDSHIP_CRITERIA_NOT_MET` | 409 Conflict |
| `ERR_LIEN_EXCEEDS_CAP` | 409 Conflict |
| `ERR_PAYMENT_EXCEEDS_OUTSTANDING` | 409 Conflict |
| `ERR_POSTING_EXCEEDS_RECOVERY` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
