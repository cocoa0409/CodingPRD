# Private Adoption Agency API — Product Requirements Document

## 1. Introduction

A private adoption agency carries a child from the moment a case is opened through home-study assessment, birth-parent matching, the legally fraught collection and possible revocation of consent, interstate compact (ICPC) clearance when the child and the prospective family live in different states, physical placement of the child, a regimen of post-placement visits, and finally court finalization. Each of these milestones is governed by statute, by the agency's licensing obligations, and by an accounting trail that must reconcile escrowed funds against approved expenses and a sliding-scale agency fee. The cost of an error is not merely financial: signing a consent too early, placing a child before interstate clearance, or letting the same employee both author and approve a home study can void an adoption or expose the agency to liability.

This API is the system of record that enforces those guardrails. It models the agency, the case, and every supporting artifact as first-class resources linked by reference, and it pins down — deterministically — the order in which prerequisites are checked, the windows in which actions are permissible, and the financial invariants that must hold at every step. A central design goal is **segregation of duties**: the person who writes a recommendation cannot be the person who approves it, and the person who logs a cost cannot be the person who releases money against it. A second goal is **temporal determinism**: every time-sensitive rule is evaluated against an agency-scoped clock that advances only by explicit operator action, so the same sequence of requests always produces the same outcome. The sections that follow define the global contract first, then walk the business workflows in the order a case actually proceeds.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated by two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they are acting. If either header is missing or malformed, the request is rejected with `ERR_MISSING_USER_CONTEXT`; a `X-User-Role` value that is present but not one of the five recognized role strings is treated as malformed and likewise rejected with `ERR_MISSING_USER_CONTEXT` (not `ERR_UNAUTHORIZED`). If the headers are well-formed — both present, non-empty, and the role is one of the five recognized roles — but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly five roles, spelled precisely as follows: `AgencyAdmin`, `Supervisor`, `Caseworker`, `FinanceOfficer`, and `CompactAdministrator`. An `AgencyAdmin` is the platform operator who provisions agencies and drives system-level and clock endpoints. A `Supervisor` is a senior caseworker who opens cases, approves and returns home studies, accepts/declines/dissolves matches, manages placements, and voids invoices. A `Caseworker` is the front-line worker who registers families and birth parents, authors home studies, proposes matches, collects and signs and revokes consent, drives ICPC paperwork, schedules and completes visits, books counseling, and logs expenses. A `FinanceOfficer` manages escrow and billing — approving, rejecting, and disbursing expenses, recording escrow transactions, and issuing and paying invoices. A `CompactAdministrator` is the state ICPC compact administrator who renders sending and receiving approvals and rejections on interstate clearances.

All five roles carry an **opaque** identity. That is, for every role, `X-User-ID` is an operator identifier that is not tied to any persisted entity's `id`; the server never compares it to an entity primary key. The server does, however, record the acting `X-User-ID` onto the resource where a scaffold transition writes it — for example, as `authoring_caseworker_id` and `approving_supervisor_id` on a home study, `counselor_id` on a counseling session, `proposed_by_caseworker_id` on a match, `visiting_caseworker_id` on a visit, `logged_by_caseworker_id` and `approved_by_finance_id` on an expense, and `recorded_by_finance_id` on an escrow transaction. These recorded operator identifiers are precisely what segregation-of-duties checks compare against one another (see §2.5); they are never matched against any resource's `id`.

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

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A `limit` below 1, a `limit` above 100, or a negative `offset` is rejected with `ERR_INVALID_PAGINATION`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Paginated list responses always include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties and the Agency Clock

Nearly every resource in the system shares a standard set of system-managed fields. The `id` is a unique, server-minted UUID carrying no type prefix. The `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` is an ISO 8601 UTC timestamp, likewise with three fractional digits, refreshed on every mutation to the resource. The `version` is a system-managed integer that begins at its initial value and increments by one with every modification; it is the basis for optimistic concurrency control described in §2.6.

There is one exception. The escrow transaction is an immutable ledger record: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because it is never modified after it is written. Every other resource — agency, case, adoptive family, home study, birth parent, counseling session, match, consent record, ICPC clearance, placement, post-placement visit, expense entry, and agency fee invoice — carries the full quartet of `id`, `created_at`, `updated_at`, and `version`.

All time-sensitive logic in the system is evaluated not against real wall-clock time but against a **deterministic agency clock**. Each agency carries a `current_utc` field representing its logical "now". At agency creation this defaults to the creation time, and thereafter it advances only when an operator explicitly sets it. Every timestamp the server stamps onto a resource — a home study's `completed_at`, a consent's `signed_at`, an ICPC clearance's `submitted_at`, a placement's `placed_at` and `finalized_at`, a visit's `conducted_at` — is read from this clock, and every temporal comparison (expiry, consent eligibility, revocation windows, visit windows) is made against it.

### 2.5. Segregation of Duties

Two control points in the case lifecycle require that two distinct human operators participate, and the system enforces this by comparing recorded operator identifiers. First, a home study's approving `Supervisor` must not be the same operator who authored it: when a `Supervisor` approves or returns a study, the acting `X-User-ID` is compared to the study's `authoring_caseworker_id`, and if they are equal the action is rejected with `ERR_SEGREGATION_OF_DUTIES`. Second, an expense's approving `FinanceOfficer` must not be the same operator who logged it: when a `FinanceOfficer` approves an expense, the acting `X-User-ID` is compared to the expense's `logged_by_caseworker_id`, and equality is again rejected with `ERR_SEGREGATION_OF_DUTIES`. This segregation check applies to exactly three operations: home-study approve, home-study return, and expense approve.

### 2.6. Optimistic Concurrency Control on the Case

Two write operations create child records whose correctness depends on the writer holding an up-to-date view of the parent adoption case, and both are guarded by optimistic concurrency control keyed on the case's `version`.

When a `Caseworker` creates a consent record, the request body must carry `expected_case_version`, which is the client's last observed `version` of the target adoption case. If another writer has advanced the case's `version` since the client last read it — for instance, by collecting (and possibly superseding) consent on the same case, leaving the current writer's view of which prior consent to supersede stale — the create is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412). Likewise, when a `FinanceOfficer` records an escrow transaction, the request body must carry `expected_case_version`; if a prior disbursement or refund has advanced the case's `version` since the client last read it, leaving the writer's view of available funds stale, the transaction is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412). The rejection is framed purely in terms of a stale observed version, not in terms of requests overlapping in time. Both of these creates also bump the case's own `version` on success. No other endpoint accepts or requires `expected_case_version`; endpoints not named here perform no version check.

### 2.7. Path Resolution and Referential Integrity

When a request targets a resource by an identifier embedded in its URL path, the system validates that identifier first; if the addressed resource does not exist, the request is rejected with `ERR_NOT_FOUND`. Where a path contains more than one identifier, the identifiers are validated left to right, and the first one that does not resolve produces the `ERR_NOT_FOUND` rejection before any later identifier is examined. Separately, on create operations, every foreign-key reference supplied in the request body — a `case_id`, a `family_id`, a `birth_parent_id`, a `placement_id`, an `expense_id`, an `agency_id`, or a `supersedes_consent_id` — must reference an existing resource; a dangling body reference is rejected with `ERR_REFERENCED_RESOURCE_NOT_FOUND`. Required fields must be present and of the declared type, and any field constrained to an enumerated set must carry a legal value; violations are rejected with `ERR_INVALID_REQUEST`.

### 2.8. Derived-State Reconciliation and Cascades

Many resources carry **computed** fields that are not supplied by clients but are derived from related records, and the system keeps them reconciled immediately. The adoption case's `phase`, its `escrow_balance_cents`, its `reimbursable_expense_cents`, and its `interstate` flag are all derived; a placement's `required_visits` and `completed_visit_count` are derived; a home study's `expires_at` and `revision_count` are derived; a consent record's `revocation_deadline` is derived; and an agency fee invoice's `base_fee_cents`, `sliding_scale_pct`, and `total_due_cents` are derived. Whenever a child-entity transition changes a value that feeds one of these derived fields, the owning parent is recomputed in the same operation, and that recomputation is itself a mutation that refreshes the parent's `updated_at` and increments its `version`.

Every lifecycle-bearing entity exposes its current state through a `status` field (the adoption case names its lifecycle state `phase` instead), and each transition described in §3 also increments that entity's own `version` and refreshes its `updated_at`. Some transitions cascade across more than one resource. The system always applies the full cascade, not merely the primary effect. The specific cascades — consent revocation disrupting a placement and missing its visits, placement disruption missing its scheduled visits, expense disbursement writing an escrow transaction and reconciling the balance, placement finalization extinguishing residual revocation rights — are described in the workflow narratives of §3, but the governing principle is stated here: every secondary effect of an operation is part of that operation and completes before the response is returned.

### 2.9. Monetary and Temporal Precision

All monetary values in the system are integer cents. The escrow balance and the reimbursable expense total are pure integer sums and involve no rounding because all of their inputs are integers. The agency fee invoice involves a sliding-scale multiplication and therefore rounding: wherever a fractional cent arises, the system rounds half up, and — critically — the rounding is applied to each sliding-scaled component separately before the components are summed, never to the sum (see §3.8 for the full computation). All temporal values are millisecond-precision UTC instants. Where a rule lands a deadline on the end of a day, that instant is `23:59:59.000Z` of the day in question.

## 3. Business Logic & Workflows

### 3.1. Provisioning the Agency and Opening a Case

An adoption begins with an agency. An `AgencyAdmin` provisions an agency by supplying its `name`, its `licensed_state` (the two-letter state code where the agency holds its license), and its `fee_schedule_cents` (the base placement fee in cents before any sliding-scale adjustment, which must be at least 0). On creation the agency's `current_utc` is initialized to the creation instant. Because every temporal rule reads the agency clock, the system exposes an administrative test-driving capability that lets an `AgencyAdmin` advance the clock: it accepts an `agency_id` and a `to_iso8601` target instant and writes the agency's `current_utc` to that instant; the addressed `agency_id` is resolved like a path target, so a clock-set against a non-existent agency is rejected with `ERR_NOT_FOUND` (not `ERR_REFERENCED_RESOURCE_NOT_FOUND`). The set returns the updated agency, whose `version` and `updated_at` advance on the write. This is the only way the clock moves.

A `Supervisor` opens an adoption case by supplying the owning `agency_id`, a human-readable `case_label`, the `child_state` (the two-letter state where the child currently resides — the ICPC sending state), and the `family_state` (the two-letter state where the adoptive family resides — the ICPC receiving state). At creation the case's `phase` is `INTAKE`, its `escrow_balance_cents` and `reimbursable_expense_cents` are both 0, and its `interstate` flag is computed: the case is interstate exactly when `child_state` and `family_state` differ. Reading a case always returns its freshly reconciled `phase`, `escrow_balance_cents`, and `reimbursable_expense_cents`. Cases may be listed and optionally filtered by `agency_id`.

The case `phase` is never set directly; it is a projection over the case's child entities, recomputed whenever any of those children transition and also whenever the case is read. The projection is evaluated in a strictly pinned priority order, and the first matching rule wins, top to bottom. First, if any placement for the case is `FINALIZED`, the phase is `FINALIZED`. Otherwise, if any placement is `DISRUPTED` or any consent record for the case is `REVOKED`, the phase is `DISRUPTED`. Otherwise, if any placement is `ACTIVE`, the phase is `PLACED`. Otherwise, if the case is interstate and its ICPC clearance is `RECEIVING_APPROVED`, the phase is `ICPC_CLEARED`. Otherwise, if any consent record for the case is `IRREVOCABLE`, the phase is `CONSENTED`. Otherwise, if any match for the case is `ACCEPTED`, the phase is `MATCHED`. Otherwise, if any home study for the case is `APPROVED` and not expired (the agency clock is strictly before its `expires_at`), the phase is `HOME_STUDY`. If none of these holds, the phase is `INTAKE`. Note that the `ICPC_CLEARED` rule applies only to interstate cases; an in-state case skips it entirely and moves from `CONSENTED` to `PLACED` directly. An `APPROVED` home study that has since expired, with no later milestone reached, lets the case fall all the way back to `INTAKE`.

### 3.2. The Home Study and Its Revision Loop

A `Caseworker` registers the prospective family first, supplying the `case_id` it belongs to, the `primary_applicant_name`, the family's `residence_state`, the `household_size` (which must be at least 1), and the combined `annual_income_cents` (at least 0). The income figure later feeds the sliding-scale fee. With a family on file, a `Caseworker` creates a home study against a `case_id` and a `family_id`; the study opens in `DRAFT` status, and the creating operator's `X-User-ID` is recorded as its `authoring_caseworker_id`. Studies may be retrieved individually and listed, optionally filtered by `case_id` or `family_id`.

The home study moves through a review cycle. The authoring `Caseworker` submits the study, advancing it from `DRAFT` to `UNDER_REVIEW`; submission is permitted only while the study is `DRAFT` and only when the acting operator is the study's author (a submit by any other operator is rejected with `ERR_UNAUTHORIZED`, checked after the state check). From `UNDER_REVIEW`, a `Supervisor` either approves or returns the study. Approval requires the study to be `UNDER_REVIEW` and requires the acting `Supervisor` to differ from the author (segregation of duties; see §2.5). On approval the study's `approving_supervisor_id` is set to the acting operator, its `completed_at` is set to the agency clock, and its `expires_at` is computed as `completed_at` plus the validity window of 365 days (that is, `completed_at` advanced by 365 times twenty-four hours of wall-clock time). Approval also bubbles up to recompute the case `phase`. Returning a study instead advances it from `UNDER_REVIEW` to `DEFICIENT`, requires the same segregation-of-duties separation between the returning `Supervisor` and the author, and increments the study's `revision_count` by one.

A `DEFICIENT` study enters the revision loop. The author resubmits it, advancing `DEFICIENT` to `RESUBMITTED` (permitted only while `DEFICIENT`, and only for the author; a resubmit by any other operator is rejected with `ERR_UNAUTHORIZED`, checked after the state check). From `RESUBMITTED`, the author submits again, advancing `RESUBMITTED` back to `UNDER_REVIEW`, where it once more faces approval or return. This `DEFICIENT → RESUBMITTED → UNDER_REVIEW → {APPROVED | DEFICIENT}` loop may repeat, each return bumping `revision_count`. An approved study does not last forever: a system check may expire an `APPROVED` study once the agency clock reaches or passes its `expires_at`. This expiry transition requires the study to be `APPROVED` and the agency clock to be at or after `expires_at`; if the study is `APPROVED` but the clock has not yet reached `expires_at`, the check is rejected with `ERR_INVALID_STATE`. On success it moves the study to `EXPIRED` and bubbles up to recompute the case phase, which — if the case has not yet reached placement — reverts toward `HOME_STUDY` or further back. A study is usable for downstream gating only while the agency clock is strictly before its `expires_at`; at exactly `expires_at` it is expired. Any attempt to drive a transition from a state in which it is not defined is rejected with `ERR_INVALID_STATE`.

### 3.3. Birth Parents, Counseling, and the Match

A `Caseworker` registers a birth parent against an `agency_id`, recording the `legal_name`, the `birth_state` (the two-letter state where the birth occurs and the child resides at birth), and the `parent_role`, which is one of `BIRTH_MOTHER`, `BIRTH_FATHER`, or `LEGAL_GUARDIAN`. Birth parents may be retrieved and listed, optionally filtered by `agency_id`.

Birth parents receive counseling. A `Caseworker` books a counseling session by supplying the `birth_parent_id`, the `case_id`, a `start_at` instant (inclusive), and an `end_at` instant (exclusive); the booking opens in `BOOKED` status and records the booking operator as `counselor_id`. A session's `start_at` must be strictly before its `end_at`. Furthermore, for a given birth parent, two non-cancelled sessions may not fall within sixty minutes of each other. The buffer is applied as a closed interval on both sides: an existing non-cancelled session occupies the interval running from sixty minutes before its `start_at` to sixty minutes after its `end_at`. A candidate session conflicts with an existing one when the candidate's `start_at` is earlier than the existing session's `end_at` plus sixty minutes **and** the existing session's `start_at` is earlier than the candidate's `end_at` plus sixty minutes. Because the buffer is added to a closed interval, two back-to-back sessions whose candidate `start_at` exactly equals an existing `end_at` **do** conflict. A violation of either the ordering rule or the buffer rule is rejected with `ERR_SESSION_BUFFER_CONFLICT`. Only `BOOKED` and `HELD` sessions occupy the schedule; a `CANCELLED` session frees its buffered interval so a replacement may be booked in the same slot. A `Caseworker` marks a session `HELD` (permitted only from `BOOKED`, and only once the agency clock has reached or passed the session's `start_at`; an attempt to hold a `BOOKED` session before its `start_at` is rejected with `ERR_INVALID_STATE`) or cancels it to `CANCELLED` (permitted only from `BOOKED`; a `HELD` session may not be cancelled).

Matching brings the three parties together. A `Caseworker` proposes a match by supplying the `case_id`, the `family_id`, and the `birth_parent_id`; the match opens in `PROPOSED` status and records the proposer as `proposed_by_caseworker_id`. From `PROPOSED`, a `Supervisor` accepts or declines the match. Acceptance requires the match to be `PROPOSED`, requires the case's home study to be `APPROVED`, and requires that home study to be non-expired (the agency clock strictly before its `expires_at`); on success the match moves to `ACCEPTED` and the case phase is recomputed (advancing toward `MATCHED`). If the case's home study is not in the `APPROVED` state, acceptance is rejected with `ERR_PREREQUISITE_NOT_MET`; if it is `APPROVED` but the agency clock has reached or passed its `expires_at`, acceptance is rejected with `ERR_HOME_STUDY_EXPIRED`. Declining requires only that the match be `PROPOSED` and moves it to `DECLINED`. An `ACCEPTED` match may later be dissolved by a `Supervisor`, moving it to `DISSOLVED`; dissolution requires the match to be `ACCEPTED` and requires that no consent record for the case is in `IRREVOCABLE` status (a dissolve attempt while any case consent is `IRREVOCABLE` is rejected with `ERR_PREREQUISITE_NOT_MET`), and on success it recomputes the case phase (reverting toward `HOME_STUDY`).

### 3.4. Consent: Eligibility, Signing, Revocation, and Irrevocability

Consent is the most legally sensitive artifact in the system, and its lifecycle is `PENDING → SIGNED → {REVOKED | IRREVOCABLE}`. A `Caseworker` creates a consent record by supplying the `case_id`, the `birth_parent_id`, the child's date of birth `child_dob`, and the `revocation_basis` — one of `CALENDAR_DAYS` or `BUSINESS_DAYS` — which selects how the revocation deadline will be computed. The create may optionally carry `supersedes_consent_id`, a reference to a prior consent record that this one re-collects after the earlier record was revoked. The create is guarded by optimistic concurrency control: it must carry `expected_case_version`, and a mismatch with the case's current `version` is rejected with `ERR_STALE_CASE_VERSION` as described in §2.6. A successful create increments the case's `version`. Consent records may be retrieved and listed, optionally filtered by `case_id`, `birth_parent_id`, or `supersedes_consent_id`.

Signing a consent moves it from `PENDING` to `SIGNED` and is performed by a `Caseworker`. Signing requires the consent to be `PENDING`, requires the case to have an `ACCEPTED` match, and requires that enough time has elapsed since the child's birth. Birth-parent consent may not be taken until at least seventy-two hours after birth: the earliest permissible signing instant is the child's `child_dob` advanced by seventy-two hours, and signing is permitted only when the agency clock is at or after that instant — at exactly the threshold it is eligible. A signing attempt before that instant is rejected with `ERR_CONSENT_TOO_EARLY`; a signing attempt when the case lacks an `ACCEPTED` match is rejected with `ERR_PREREQUISITE_NOT_MET`. On a successful sign, the consent's `signed_at` is set to the agency clock and its `revocation_deadline` is computed from the basis variant, and the consent's `version` increments.

The revocation deadline is computed from `signed_at` according to the chosen `revocation_basis`. Under the `CALENDAR_DAYS` variant, the deadline is `signed_at` advanced by ten days of pure wall-clock time — ten times twenty-four hours — with weekends and holidays counted normally. Under the `BUSINESS_DAYS` variant, the deadline is the end of the fifth business day after signing, computed by a pinned counting rule: starting from the calendar day of `signed_at`, the system steps forward one calendar day at a time; a business day is Monday through Friday (UTC weekday 0 through 4), while Saturday and Sunday are skipped and do not consume a count; each landed business day decrements the remaining count by one; and the deadline is `23:59:59.000Z` (UTC) of the day on which the count reaches zero. The day of `signed_at` itself never counts as the first business day even when it is a weekday — counting begins on the next calendar day.

While a consent is `SIGNED`, the birth parent may revoke it within the window. A `Caseworker` revokes the consent, moving it from `SIGNED` to `REVOKED`; revocation requires the consent to be `SIGNED` and requires the agency clock to be at or before the `revocation_deadline` — the deadline instant itself is still revocable. A revocation attempt strictly after the deadline is rejected with `ERR_REVOCATION_WINDOW_CLOSED`. A successful revocation triggers a two-hop cascade: if the case has an active placement, that placement (whether `PENDING` or `ACTIVE`) transitions to `DISRUPTED`, and that placement disruption in turn transitions every `SCHEDULED` post-placement visit for the placement to `MISSED`. The revocation then bubbles up to recompute the case phase, driving the case to `DISRUPTED`, and increments the consent's `version`.

If the window passes without revocation, a system check makes the consent irrevocable. This transition requires the consent to be `SIGNED` and requires the agency clock to be strictly after the `revocation_deadline`; if the consent is `SIGNED` but the clock is at or before the `revocation_deadline`, the check is rejected with `ERR_INVALID_STATE`. On success it moves the consent to `IRREVOCABLE`, recomputes the case phase (with an `IRREVOCABLE` consent the case advances to `CONSENTED` unless a later milestone already applies), and increments the consent's `version`.

### 3.5. Interstate Compact (ICPC) Clearance

When a child and family live in different states, the adoption must clear the Interstate Compact on the Placement of Children before the child may be placed. A `Caseworker` opens an ICPC clearance for a `case_id`; on creation the clearance copies the case's `child_state` into its `sending_state` and the case's `family_state` into its `receiving_state`, and its initial status depends on the case: it opens in `DRAFT` when the case is interstate and in `NOT_REQUIRED` when the case is in-state. Clearances may be retrieved and listed, optionally filtered by `case_id`.

The clearance progresses `DRAFT → SUBMITTED → SENDING_APPROVED → RECEIVING_APPROVED`, with a rejection-and-rework branch. A `Caseworker` submits the packet, moving it from `DRAFT` to `SUBMITTED`; submission requires the clearance to be `DRAFT` and requires the case to have an `ACCEPTED` match. Because an in-state case's clearance opens in `NOT_REQUIRED` (never `DRAFT`) and `submit` is defined only from the `DRAFT` state, an attempt to submit on an in-state case is caught by the state-transition check and rejected with `ERR_INVALID_STATE` — the `ERR_ICPC_NOT_APPLICABLE` interstate-applicability check, which per §3.9 is evaluated only after the state check has passed, is therefore never reached on this submit path. Submitting when the case lacks an `ACCEPTED` match is rejected with `ERR_PREREQUISITE_NOT_MET`. On a successful submit the clearance's `submitted_at` is set to the agency clock. A `CompactAdministrator` then renders the sending-state approval, moving `SUBMITTED` to `SENDING_APPROVED`, and afterward the receiving-state approval, moving `SENDING_APPROVED` to `RECEIVING_APPROVED`; the receiving approval bubbles up to recompute the case phase (advancing toward `ICPC_CLEARED`). A `CompactAdministrator` may instead reject the clearance — permitted while it is `SUBMITTED` or `SENDING_APPROVED` — moving it to `REJECTED`. A `Caseworker` reworks a rejected clearance, moving it from `REJECTED` back to `DRAFT` and clearing its `submitted_at` back to null so the packet may be re-submitted. Every ICPC transition increments the clearance's `version`.

### 3.6. Placement, Post-Placement Visits, Finalization, and Disruption

A placement is the physical placing of the child in the home, and it is gated by the convergence of consent, interstate clearance, and a valid home study. A `Supervisor` creates a placement by supplying the `case_id` and the `family_id`; it opens in `PENDING`. Placements may be retrieved and listed, optionally filtered by `case_id` or `family_id`, and a placement read always returns its freshly reconciled `required_visits` and `completed_visit_count`.

Activating a placement moves it from `PENDING` to `ACTIVE` and is performed by a `Supervisor`. Activation requires the placement to be `PENDING` and imposes three cross-entity gates: the case must have at least one consent record in `IRREVOCABLE` status (the gate is satisfied by any `IRREVOCABLE` consent on the case and is not scoped to a particular birth parent); if the case is interstate, its ICPC clearance must be `RECEIVING_APPROVED`; and the case's home study must be `APPROVED` with the agency clock strictly before its `expires_at`. A missing or wrong-state prerequisite — consent not `IRREVOCABLE`, ICPC not `RECEIVING_APPROVED` on an interstate case, or home study not `APPROVED` — is rejected with `ERR_PREREQUISITE_NOT_MET`; the special case where the home study is `APPROVED` but the agency clock has reached or passed its `expires_at` is rejected with `ERR_HOME_STUDY_EXPIRED`. On success the placement's `placed_at` is set to the agency clock, its `required_visits` is computed, and the case phase is recomputed to `PLACED`. The number of required visits depends on whether the case is interstate: an interstate case requires six post-placement visits, while an in-state case requires three; the case is interstate exactly when its `child_state` differs from its `family_state`.

A `Caseworker` schedules a post-placement visit by supplying the `case_id`, the `placement_id`, a `window_start` instant (inclusive), and a `window_end` instant (exclusive); the visit opens in `SCHEDULED` and records the scheduling operator as `visiting_caseworker_id`. A visit's `window_start` must be strictly before its `window_end`, and two `SCHEDULED` visits for the same placement may not overlap. The visit window is half-open and touching is allowed: an existing visit occupies its window up to but not including its `window_end`, so a new visit whose `window_start` exactly equals an existing visit's `window_end` does not overlap. Two visits overlap when the new visit's `window_start` is earlier than the existing visit's `window_end` **and** the existing visit's `window_start` is earlier than the new visit's `window_end`. An invalid or overlapping schedule is rejected with `ERR_VISIT_OVERLAP`. A `Caseworker` completes a visit, moving it from `SCHEDULED` to `COMPLETED`; completion requires the visit to be `SCHEDULED`, requires the visit's parent placement to be `ACTIVE` (a completion attempt while the placement is not `ACTIVE` is rejected with `ERR_PREREQUISITE_NOT_MET`, checked after the state check and before the window check), and requires the agency clock to fall within the half-open window — at or after `window_start` and strictly before `window_end`. A completion attempt outside that window is rejected with `ERR_VISIT_WINDOW_INVALID`. On completion the visit's `conducted_at` is set to the agency clock, and the parent placement's `completed_visit_count` is incremented by recomputing it as the count of the placement's visits in `COMPLETED` status. Alternatively, a system check marks a visit `MISSED` once its window has closed: this requires the visit to be `SCHEDULED` and the agency clock to be at or after `window_end`, and moves it to `MISSED`; an attempt to mark a `SCHEDULED` visit missed before the clock reaches `window_end` is rejected with `ERR_INVALID_STATE`.

Finalization is the court's blessing of the adoption. A `Supervisor` finalizes a placement, moving it from `ACTIVE` to `FINALIZED`; finalization requires the placement to be `ACTIVE`, requires the placement's `completed_visit_count` to be at least its `required_visits`, and requires that an agency fee invoice exists for the case in either `ISSUED` or `PAID` status (a placement cannot be finalized while its fee invoice is `VOID`, and an invoice must exist). If too few visits have been completed, finalization is rejected with `ERR_VISITS_INCOMPLETE`; the visit-count check is evaluated first, and only if it passes is the invoice requirement checked, with the absence of any `ISSUED`-or-`PAID` invoice (none exists, or all are `VOID`) rejected with `ERR_PREREQUISITE_NOT_MET`. On success the placement's `finalized_at` is set to the agency clock, the case phase is recomputed to `FINALIZED`, and — because finalization extinguishes any residual revocation rights — every `SIGNED` consent record for the case is transitioned to `IRREVOCABLE`.

A `Supervisor` may instead disrupt an active placement, moving it from `ACTIVE` to `DISRUPTED`; disruption requires the placement to be `ACTIVE`, transitions every `SCHEDULED` post-placement visit for the placement to `MISSED`, and recomputes the case phase to `DISRUPTED`.

### 3.7. Expense Logging, Approval, Escrow, and Disbursement

Costs accrue against a case and flow through escrow. A `Caseworker` logs an expense by supplying the `case_id`, the `category` — one of `MEDICAL`, `LEGAL`, `LIVING`, `COUNSELING`, `TRAVEL`, or `OTHER` — and the `amount_cents`, which must be greater than 0; the expense opens in `LOGGED` and records the logging operator as `logged_by_caseworker_id`. Expenses may be retrieved and listed, optionally filtered by `case_id`. A `FinanceOfficer` approves an expense (moving `LOGGED` to `APPROVED`) or rejects it (moving `LOGGED` to `REJECTED`). Approval requires the expense to be `LOGGED` and requires the acting `FinanceOfficer` to differ from the `logged_by_caseworker_id` (segregation of duties; see §2.5). On approval the expense's `approved_by_finance_id` is set to the acting operator and the case's `reimbursable_expense_cents` is recomputed.

The reimbursable expense total for a case is the sum of `amount_cents` over the case's expenses whose status is `APPROVED` or `DISBURSED`; expenses that are `LOGGED` or `REJECTED` are excluded, and disbursement does not remove an expense from the total because it remains in an approved-or-disbursed status.

Escrow holds the money. A `FinanceOfficer` records an escrow transaction by supplying the `case_id`, the `txn_type` — one of `DEPOSIT`, `DISBURSEMENT`, or `REFUND` — the `amount_cents` (greater than 0), and optionally an `expense_id` (set for disbursement transactions tied to an approved expense). The recording operator is captured as `recorded_by_finance_id`. As described in §2.6, this create is OCC-guarded: it requires `expected_case_version` and a mismatch is rejected with `ERR_STALE_CASE_VERSION`; a successful create recomputes the case's `escrow_balance_cents` and increments the case's `version`. The escrow balance for a case is the sum of `amount_cents` over its `DEPOSIT` transactions, minus the sum over its `DISBURSEMENT` transactions, minus the sum over its `REFUND` transactions. A transaction that would drive `escrow_balance_cents` below zero — a disbursement or refund whose amount exceeds the available balance — is rejected with `ERR_INSUFFICIENT_ESCROW`.

Disbursing an approved expense ties the two ledgers together. A `FinanceOfficer` disburses an expense, moving it from `APPROVED` to `DISBURSED`; disbursement requires the expense to be `APPROVED` and requires the case's `escrow_balance_cents` to be at least the expense's `amount_cents`. If the balance is short, the disbursement is rejected with `ERR_INSUFFICIENT_ESCROW`. A successful disbursement triggers a two-hop cascade: it creates a `DISBURSEMENT` escrow transaction for the expense's amount tied to that expense, and that transaction in turn recomputes the case's `escrow_balance_cents`. A disbursement of amount A decreases `escrow_balance_cents` by exactly A while the matching expense moves to `DISBURSED`. The balance is governed solely by the operational formula above (`DEPOSIT` sum minus `DISBURSEMENT` sum minus `REFUND` sum), and a `REFUND` is therefore a further deduction, not a credit: a `REFUND` of amount A applied after such a disbursement decreases `escrow_balance_cents` by an additional A (it does not restore the balance to its pre-disbursement value). The total agency-held funds always equal the current escrow balance plus the sum of everything disbursed.

### 3.8. The Agency Fee Invoice and the Sliding Scale

When the agency is ready to bill, a `FinanceOfficer` issues an agency fee invoice for a `case_id`; it opens in `ISSUED` and its monetary fields are computed at issuance. The invoice's `base_fee_cents` captures the agency's `fee_schedule_cents` at the moment of issuance, its `sliding_scale_pct` captures the income-band adjustment as a signed decimal fraction (one of `-0.2`, `0.0`, or `0.15`, serialized as a JSON number — not a whole-number percentage), and its `total_due_cents` is the combinatorial total computed as follows. Issuance imposes no state prerequisites: an invoice may be issued against a case in any phase, and any number of invoices may be issued for the same case. Invoices may be retrieved and listed, optionally filtered by `case_id`.

The computation reads three inputs: the base, which is the agency's `fee_schedule_cents`; the family's `annual_income_cents`, drawn from the adoptive family registered against the case (when more than one family is registered, the earliest-created one is used; when none is registered, the income is treated as 0, which lands in the discount band); and the case's `reimbursable_expense_cents` (the sum of its `APPROVED` and `DISBURSED` expenses). It proceeds in pinned order. First, the sliding-scale fraction is selected by an income-band threshold: when the family's annual income is below forty thousand dollars (4,000,000 cents), the fraction is negative twenty hundredths, representing a 20% discount; when the income is at least forty thousand dollars but below one hundred twenty thousand dollars (12,000,000 cents), the fraction is zero; and when the income is at least one hundred twenty thousand dollars, the fraction is positive fifteen hundredths, representing a 15% surcharge. Second, the reimbursable pass-through is capped: the billable reimbursable amount is the smaller of the case's reimbursable expense total and the cap of fifteen thousand dollars (1,500,000 cents). Third, the same sliding-scale fraction is applied to both components and each is rounded separately: the adjusted base is the base multiplied by one plus the fraction, rounded half up to whole cents; the adjusted reimbursable is the capped billable reimbursable multiplied by one plus the fraction, rounded half up to whole cents. Fourth, the total due is the adjusted base plus the adjusted reimbursable. The rounding order is pinned to round-each-component-then-sum; the system must not instead sum the two scaled components first and round once, because the two orders diverge whenever both components carry a half-cent.

An issued invoice may be paid by a `FinanceOfficer`, moving it from `ISSUED` to `PAID`, or voided by a `Supervisor`, moving it from `ISSUED` to `VOID`. Voiding requires the invoice to be `ISSUED` and requires that no placement for the case is `FINALIZED` — a fee on a finalized case cannot be voided; a void attempt when any case placement is `FINALIZED` is rejected with `ERR_PREREQUISITE_NOT_MET`.

### 3.9. Validation Precedence

When a single operation could fail several checks at once, the checks are evaluated in a fixed precedence so that the reported error is deterministic. User-context presence and well-formedness comes first (`ERR_MISSING_USER_CONTEXT`), then role authorization (`ERR_UNAUTHORIZED`), then — on list endpoints — pagination-range validation (`ERR_INVALID_PAGINATION`), then existence of every path-referenced resource validated left to right (`ERR_NOT_FOUND`), then existence of every body foreign key (`ERR_REFERENCED_RESOURCE_NOT_FOUND`), then presence/type/enum validity of request fields (`ERR_INVALID_REQUEST`), then whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). Only after those structural checks pass does the system evaluate business rules: segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), then cross-entity sibling-state prerequisites (`ERR_PREREQUISITE_NOT_MET`), then the home-study expiry check (`ERR_HOME_STUDY_EXPIRED`, which on match-accept and placement-activate is evaluated after the `APPROVED`-state prerequisite and before consent-timing rules), then consent-timing (`ERR_CONSENT_TOO_EARLY`), then revocation-window (`ERR_REVOCATION_WINDOW_CLOSED`), then visit-window (`ERR_VISIT_WINDOW_INVALID`), then the finalize visit-count constraint (`ERR_VISITS_INCOMPLETE`), then scheduling-overlap constraints (`ERR_VISIT_OVERLAP` and `ERR_SESSION_BUFFER_CONFLICT`), then ICPC applicability (`ERR_ICPC_NOT_APPLICABLE`), then the fiscal escrow-sufficiency check (`ERR_INSUFFICIENT_ESCROW`), and finally the optimistic-concurrency case-version check (`ERR_STALE_CASE_VERSION`).

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including every state-transition action and the clock-setting capability — return a `200 OK` status code. Readers should reconstruct each endpoint's request body, computed effects, and cascades from the workflow narratives in §3; the table below carries only the routing and authorization contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/agencies` | Create an agency | AgencyAdmin |
| GET | `/agencies/{id}` | Get an agency | AgencyAdmin, Supervisor, Caseworker, FinanceOfficer, CompactAdministrator |
| GET | `/agencies` | List agencies | AgencyAdmin |
| POST | `/_clock/set_current_utc` | Set the agency deterministic clock (test-driving) | AgencyAdmin |
| POST | `/cases` | Open an adoption case | Supervisor |
| GET | `/cases/{id}` | Get a case (derived phase, escrow, reimbursable totals) | Supervisor, Caseworker, FinanceOfficer, CompactAdministrator |
| GET | `/cases` | List cases (filter by agency) | Supervisor, Caseworker, FinanceOfficer |
| POST | `/families` | Register an adoptive family on a case | Caseworker |
| GET | `/families/{id}` | Get a family | Supervisor, Caseworker, FinanceOfficer |
| GET | `/families` | List families (filter by case) | Supervisor, Caseworker |
| POST | `/home-studies` | Create a home study (DRAFT) | Caseworker |
| GET | `/home-studies/{id}` | Get a home study | Supervisor, Caseworker |
| GET | `/home-studies` | List home studies (filter by case or family) | Supervisor, Caseworker |
| POST | `/home-studies/{id}/submit` | Submit study for review | Caseworker |
| POST | `/home-studies/{id}/approve` | Approve study | Supervisor |
| POST | `/home-studies/{id}/return` | Return study as deficient | Supervisor |
| POST | `/home-studies/{id}/resubmit` | Begin revision | Caseworker |
| POST | `/home-studies/{id}/check-expiry` | System check: expire an APPROVED study past its expiry | AgencyAdmin |
| POST | `/birth-parents` | Register a birth parent | Caseworker |
| GET | `/birth-parents/{id}` | Get a birth parent | Supervisor, Caseworker |
| GET | `/birth-parents` | List birth parents (filter by agency) | Supervisor, Caseworker |
| POST | `/counseling-sessions` | Book a birth-parent counseling session (BOOKED) | Caseworker |
| GET | `/counseling-sessions/{id}` | Get a counseling session | Supervisor, Caseworker |
| GET | `/counseling-sessions` | List counseling sessions (filter by birth parent or case) | Supervisor, Caseworker |
| POST | `/counseling-sessions/{id}/hold` | Mark a session held | Caseworker |
| POST | `/counseling-sessions/{id}/cancel` | Cancel a session | Caseworker |
| POST | `/matches` | Propose a match (PROPOSED) | Caseworker |
| GET | `/matches/{id}` | Get a match | Supervisor, Caseworker |
| GET | `/matches` | List matches (filter by case) | Supervisor, Caseworker |
| POST | `/matches/{id}/accept` | Accept a match | Supervisor |
| POST | `/matches/{id}/decline` | Decline a match | Supervisor |
| POST | `/matches/{id}/dissolve` | Dissolve an accepted match | Supervisor |
| POST | `/consent-records` | Create a consent record (PENDING); OCC-guarded on case | Caseworker |
| GET | `/consent-records/{id}` | Get a consent record | Supervisor, Caseworker |
| GET | `/consent-records` | List consent records (filter by case or birth parent) | Supervisor, Caseworker |
| POST | `/consent-records/{id}/sign` | Sign consent (PENDING -> SIGNED) | Caseworker |
| POST | `/consent-records/{id}/revoke` | Revoke consent within window (SIGNED -> REVOKED) | Caseworker |
| POST | `/consent-records/{id}/finalize-consent` | System: make consent irrevocable past deadline | AgencyAdmin |
| POST | `/icpc-clearances` | Open an ICPC clearance for a case | Caseworker |
| GET | `/icpc-clearances/{id}` | Get an ICPC clearance | Supervisor, Caseworker, CompactAdministrator |
| GET | `/icpc-clearances` | List ICPC clearances (filter by case) | Supervisor, Caseworker, CompactAdministrator |
| POST | `/icpc-clearances/{id}/submit` | Submit packet (DRAFT -> SUBMITTED) | Caseworker |
| POST | `/icpc-clearances/{id}/approve-sending` | Sending-state approval | CompactAdministrator |
| POST | `/icpc-clearances/{id}/approve-receiving` | Receiving-state approval | CompactAdministrator |
| POST | `/icpc-clearances/{id}/reject` | Reject clearance | CompactAdministrator |
| POST | `/icpc-clearances/{id}/rework` | Rework rejected clearance (REJECTED -> DRAFT) | Caseworker |
| POST | `/placements` | Create a placement (PENDING) | Supervisor |
| GET | `/placements/{id}` | Get a placement (derived visit counts) | Supervisor, Caseworker |
| GET | `/placements` | List placements (filter by case) | Supervisor, Caseworker |
| POST | `/placements/{id}/activate` | Place the child (PENDING -> ACTIVE) | Supervisor |
| POST | `/placements/{id}/finalize` | Court finalization (ACTIVE -> FINALIZED) | Supervisor |
| POST | `/placements/{id}/disrupt` | Disrupt an active placement (ACTIVE -> DISRUPTED) | Supervisor |
| POST | `/post-placement-visits` | Schedule a post-placement visit (SCHEDULED) | Caseworker |
| GET | `/post-placement-visits/{id}` | Get a visit | Supervisor, Caseworker |
| GET | `/post-placement-visits` | List visits (filter by case or placement) | Supervisor, Caseworker |
| POST | `/post-placement-visits/{id}/complete` | Complete a visit within its window | Caseworker |
| POST | `/post-placement-visits/{id}/mark-missed` | System: mark a visit missed after its window closes | AgencyAdmin |
| POST | `/expense-entries` | Log an expense (LOGGED) | Caseworker |
| GET | `/expense-entries/{id}` | Get an expense | Supervisor, Caseworker, FinanceOfficer |
| GET | `/expense-entries` | List expenses (filter by case) | Supervisor, Caseworker, FinanceOfficer |
| POST | `/expense-entries/{id}/approve` | Approve an expense (LOGGED -> APPROVED) | FinanceOfficer |
| POST | `/expense-entries/{id}/reject` | Reject an expense (LOGGED -> REJECTED) | FinanceOfficer |
| POST | `/expense-entries/{id}/disburse` | Disburse an approved expense from escrow | FinanceOfficer |
| POST | `/escrow-transactions` | Record an escrow deposit/refund/disbursement; OCC-guarded on case | FinanceOfficer |
| GET | `/escrow-transactions/{id}` | Get an escrow transaction | Supervisor, FinanceOfficer |
| GET | `/escrow-transactions` | List escrow transactions (filter by case or expense) | Supervisor, FinanceOfficer |
| POST | `/agency-fee-invoices` | Issue an agency fee invoice (ISSUED) | FinanceOfficer |
| GET | `/agency-fee-invoices/{id}` | Get an invoice | Supervisor, FinanceOfficer |
| GET | `/agency-fee-invoices` | List invoices (filter by case) | Supervisor, FinanceOfficer |
| POST | `/agency-fee-invoices/{id}/pay` | Mark invoice paid (ISSUED -> PAID) | FinanceOfficer |
| POST | `/agency-fee-invoices/{id}/void` | Void an invoice (ISSUED -> VOID) | Supervisor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 400 Bad Request |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCED_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_PREREQUISITE_NOT_MET` | 409 Conflict |
| `ERR_CONSENT_TOO_EARLY` | 409 Conflict |
| `ERR_REVOCATION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_VISIT_WINDOW_INVALID` | 409 Conflict |
| `ERR_VISIT_OVERLAP` | 409 Conflict |
| `ERR_SESSION_BUFFER_CONFLICT` | 409 Conflict |
| `ERR_VISITS_INCOMPLETE` | 409 Conflict |
| `ERR_ICPC_NOT_APPLICABLE` | 409 Conflict |
| `ERR_INSUFFICIENT_ESCROW` | 409 Conflict |
| `ERR_STALE_CASE_VERSION` | 412 Precondition Failed |
| `ERR_HOME_STUDY_EXPIRED` | 409 Conflict |
| `ERR_INVALID_PAGINATION` | 400 Bad Request |
