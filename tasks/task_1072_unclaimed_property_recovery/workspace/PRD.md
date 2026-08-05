# Unclaimed-Property Recovery & Compliance API — Product Requirements Document

## 1. Introduction

Every U.S. jurisdiction obliges banks, insurers, utilities, and brokers to surrender the dormant property of owners they can no longer reach — forgotten accounts, uncashed checks, unclaimed insurance benefits — to the state, which then holds that value in custody until the rightful owner (or a licensed locator acting on the owner's behalf) comes forward to claim it. This API is the system of record for that full compliance lifecycle. It tracks the institutions that hold property, the property itself as it ages into dormancy, the due-diligence outreach a holder must attempt before surrendering it, the annual reports through which property is remitted to a jurisdiction, and the claims through which owners recover what is theirs.

The system serves several constituencies with sharply separated authority. Reporting institutions record and report property; state examiners review reports, adjudicate claims, and conduct audits; state approvers authorize and disburse payouts; and owners and their recovery firms pursue claims. Because the same value moves from a holder, into a jurisdiction's custody account, and back out to a claimant — sometimes only to be clawed back when a payment is voided — the platform maintains a strict, append-only custody ledger and enforces that money is conserved at every step. A single mis-timed dormancy calculation, an unreconciled remittance total, or an approver who also examined a claim can compromise the integrity of a state's unclaimed-property program, so the API encodes these guardrails as first-class, non-negotiable rules.

This document specifies the complete contract: the global conventions every endpoint obeys, the business workflows that move property and money through the system, the full endpoint surface, and the catalogue of error conditions.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope conventions, and cross-cutting principles that govern every endpoint. Business-specific workflows build on these foundations in Section 3.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or presenting an `X-User-Role` that is not one of the recognized roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the declared role is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly six roles: `StateAdmin`, `Holder`, `Owner`, `RecoveryAgent`, `StateExaminer`, and `StateApprover`.

The way `X-User-ID` binds to persisted data differs by role:

- When `X-User-Role` is `Holder`, `X-User-ID` is the `id` of the acting `Holder`; ownership checks on any resource that references a `Holder` (for example a `Property`, a `HolderReport`, or an `AuditCase`) compare that resource's holder foreign key to `X-User-ID`.
- When `X-User-Role` is `Owner`, `X-User-ID` is the `id` of the acting `Owner`; ownership checks on a resource that references an `Owner` (for example a `Claim` via its `claimant_owner_id`) compare that reference to `X-User-ID`.
- When `X-User-Role` is `RecoveryAgent`, `X-User-ID` is the `id` of the acting `RecoveryFirm`; ownership checks on a resource that references a firm (for example a `Claim` via its `recovery_firm_id`) compare that reference to `X-User-ID`.
- When `X-User-Role` is `StateAdmin`, `StateExaminer`, or `StateApprover`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as a claim's `examiner_user_id` when an examiner takes up a claim, as a claim's `approver_user_id` when an approver authorizes it, as an evidence document's `reviewed_by_user_id` when an examiner reviews it, or as an audit case's `examiner_user_id` when an examiner opens it — but it never compares that opaque identifier to any entity's `id`.

The distinction between the two opaque state roles matters for the segregation-of-duties rule described in Section 2.10: the recorded `examiner_user_id` and `approver_user_id` are compared to each other, not to any entity identity.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set and defaults to 0.

Unless a specific endpoint states otherwise, list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Every list-based response includes the following fields inside the envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in the system carry a standard set of server-managed fields:

- `id` — a server-minted UUID with no type prefix, unique across all resources.
- `created_at` — an ISO 8601 UTC timestamp (with three fractional digits) recording when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp recording the most recent modification; it is refreshed on every mutation of the resource.
- `version` — an integer that starts at 1 on creation and increments by one on every mutation. It underpins the optimistic-concurrency mechanism of Section 2.9.

Two resource kinds are deliberately lightweight and do **not** carry `updated_at` or `version`: a `PropertyType` and a `LedgerEntry` each expose only `id` and `created_at`. A `PropertyType` is a configuration record that is not mutated after creation, and a `LedgerEntry` is an immutable, append-only accounting record — once written, it is never edited. All other resources (`Holder`, `StateAccount`, `Owner`, `RecoveryFirm`, `Property`, `DueDiligenceNotice`, `HolderReport`, `Claim`, `EvidenceDocument`, `AuditCase`) carry the full four-field set.

Whenever the server recomputes a derived field on a resource — for example a report's `property_count` and `total_remitted_cents`, a holder's `audit_hold` or `assessed_penalty_cents`, or a state account's `custody_balance_cents` — that recomputation is a mutation of the owning resource and therefore refreshes its `updated_at` and increments its `version` where those fields exist.

### 2.5. The Logical Clock and All Temporal Reasoning

The system does not read the host machine's wall clock for any business rule. Instead it maintains a **logical clock** whose startup default is exactly `2026-05-01T00:00:00Z`; before any clock-setting call is made, every read of the current instant returns precisely this default. A `StateAdmin` may advance or set the logical clock by supplying a target instant as `to_iso8601`. Every temporal computation in the system — a property's dormancy date, accrued statutory interest, the spacing between due-diligence notices, and the elapsed-days due-diligence window — is evaluated against this logical clock's current value at the moment the operation is processed.

Timestamps the system stamps onto records — a notice's `sent_at`, an owner response's `responded_at`, a report's `submitted_at` — are always set to the current logical-clock instant at the time of the action.

### 2.6. The Custody Ledger and Monetary Precision

All monetary quantities in the system are held as integer **cents**; there are no fractional cents. Every movement of value into or out of a jurisdiction's custody is recorded as an immutable `LedgerEntry` whose `entry_type` is one of `REMIT_IN`, `PAYOUT_OUT`, `FEE_OUT`, or `CLAWBACK_IN`. Each entry stores an unsigned `amount_cents` magnitude (never negative), and the sign of the movement is implied entirely by its `entry_type`: `REMIT_IN` and `CLAWBACK_IN` add to custody, while `PAYOUT_OUT` and `FEE_OUT` remove from it. Each entry also records the account it posts to via `state_account_id` and, where applicable, the originating `property_id`, `ref_claim_id`, and `ref_report_id` (any of which is null when the entry is not driven by that kind of resource).

A `StateAccount`'s `custody_balance_cents` is never stored as an independently mutated number; it is defined as the signed sum over all ledger entries posted to that account — the total of the `amount_cents` of its `REMIT_IN` and `CLAWBACK_IN` entries, minus the total of the `amount_cents` of its `PAYOUT_OUT` and `FEE_OUT` entries. The balance is recomputed from the ledger on every ledger write and is always exact integer cents.

Wherever a rule requires rounding a computed money amount to whole cents — statutory interest, recovery fees, administrative deductions, and per-property remittance — the system rounds using the **round-half-up** convention (a value exactly at the half-cent rounds upward). Rounding is applied at each pinned step of a calculation in the order the calculation specifies, never deferred to the end unless the calculation says so.

### 2.7. Escheat Jurisdiction and Cross-State Consistency

Unclaimed property does not escheat to an arbitrary jurisdiction. When a `Property` is recorded, the system computes its `escheat_state` — the two-letter jurisdiction the property will surrender to — by a fixed priority rule: if the property's `owner_last_known_state` is present and non-empty, the escheat jurisdiction is that state; otherwise it falls back to the incorporation jurisdiction of the holding institution (the holder's `incorporation_state`). This determination is made once, at creation time, and stored.

Because a property can only be reported to the jurisdiction it actually escheats to, the system enforces cross-state consistency at reporting time: a property may be attached to a report only when the property's `escheat_state` equals that report's `report_state`. A mismatch is rejected with `ERR_ESCHEAT_STATE_MISMATCH` (HTTP 422). Custody credits and debits always post to the `StateAccount` whose `state_code` is the property's `escheat_state`.

### 2.8. Cascading State Effects and Custody Conservation

Several operations in the system mutate more than one resource, and every such cascade must complete as a whole. Accepting a holder report escheats each attached property and, for each, writes a custody credit and refreshes the receiving account's balance — a three-level chain from report to property to ledger and account. Paying an approved claim advances the underlying property to a claimed state and writes the corresponding custody debits. The precise transitions and ledger movements are specified in Section 3, but the system-wide guarantee is that a cascade's secondary effects (property status changes, ledger writes, balance recomputations, parent-version bumps) are applied together with its primary effect.

The platform upholds a **custody-conservation invariant**: value that entered custody and was later paid out can be restored exactly if the payment is undone. Voiding a paid claim is a compensating action — it reverses the property's claimed status and writes a clawback entry that returns to custody the full amount that had been paid out and deducted as fees, so the account balance is made whole. No operation ever edits or deletes an existing ledger entry to achieve a reversal; reversals are always expressed as new, offsetting entries.

### 2.9. Optimistic Concurrency Control on Report Attachment

Attaching a property to a draft report is guarded by optimistic concurrency control on the parent report. The attach request must carry `expected_report_version` bearing the `version` of the target `HolderReport` that the client last observed. If that value does not equal the report's current `version`, the request is rejected with `ERR_STALE_REPORT_VERSION` (HTTP 412), and no property is attached.

This guard exists because each successful attach recomputes the report's derived `property_count` and `total_remitted_cents` and bumps the report's `version` by one. A client that computed an intended filing total from an earlier snapshot of the report, then attaches a second, otherwise-eligible property while still carrying the stale version, would be filing against an out-of-date picture; the stale-version rejection forces it to re-read the report before proceeding. This is the only endpoint that consumes a client-supplied version; every other mutation is processed without a version field.

### 2.10. Segregation of Duties

State adjudication of a claim separates the examiner from the approver. When a `StateExaminer` takes up a filed claim, the system records that operator's `X-User-ID` as the claim's `examiner_user_id`. Later, when a `StateApprover` approves or pays that claim, the acting operator's `X-User-ID` must differ from the recorded `examiner_user_id`. If they are equal, the operation is rejected with `ERR_SOD_VIOLATION` (HTTP 403). This single-person-integrity rule applies to both the approve and the pay steps of a claim, so the same person can never both examine and then authorize disbursement of the same claim.

### 2.11. Nested Reads and Left-to-Right Existence Validation

Some read endpoints address a resource through a parent — for example the due-diligence notices of a property, or the evidence documents of a claim, or a specific evidence document under a specific claim. For any request whose path or body carries one or more resource identifiers, the system validates them from left to right and rejects on the first identifier that does not resolve, returning the not-found error specific to that entity kind (`ERR_HOLDER_NOT_FOUND`, `ERR_PROPERTY_TYPE_NOT_FOUND`, `ERR_STATE_ACCOUNT_NOT_FOUND`, `ERR_OWNER_NOT_FOUND`, `ERR_FIRM_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_EVIDENCE_NOT_FOUND`, or `ERR_AUDIT_NOT_FOUND`), each HTTP 404. Foreign keys supplied in a request body are validated the same way. A malformed request — a missing required field, a value of the wrong shape, or an unrecognized enum member — is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.12. Order of Validation

When several checks could reject a single request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication is checked first: a missing or unknown-role header yields `ERR_UNAUTHENTICATED`. Authorization is checked second: a known role lacking permission for the endpoint yields `ERR_UNAUTHORIZED`. Existence is checked third: every path identifier and every body foreign key must resolve, left to right, else the corresponding not-found error. State validity is checked fourth: if the target resource is not in a state from which the requested transition is defined, the request is rejected with `ERR_INVALID_STATE` (HTTP 409). Only after these universal gates pass does the system evaluate the endpoint-specific business rules described in Section 3; where those rules themselves have a relative order, that order is stated with the workflow they guard.

## 3. Business Logic & Workflows

### 3.1. Establishing the Compliance Landscape

Before any property can move through the system, a `StateAdmin` seeds the reference data every later workflow depends on. Holders are registered with their `legal_name`, their `incorporation_state` (two uppercase letters, such as NY, CA, or TX — the escheat fallback jurisdiction of Section 2.7), and a `holder_type` that must be one of `BANK`, `INSURER`, `UTILITY`, `BROKER`, or `OTHER`. A freshly registered holder begins with `status` `ACTIVE`, an `audit_hold` of false, and an `assessed_penalty_cents` running total of zero.

Property categories are defined as **property types**, each carrying a `code` (a short category code such as AC01 or MO02, unique across all property types), a human-readable `name`, and the rules that drive its dormancy and interest treatment. A property type declares how many whole years of inactivity precede dormancy in `dormancy_period_years` (a whole number of at least 1) and which date that clock counts from in `dormancy_basis`, which is either `LAST_ACTIVITY` or `ISSUANCE`. It also declares whether escheated remittance accrues statutory interest via the `interest_bearing` flag, whether a due-diligence notice must be sent before reporting via `due_diligence_required`, and, when outreach is required, the minimum number of days that must pass after the first notice before the property may be reported via `due_diligence_min_days` (a whole number of at least 0).

A `StateAdmin` also opens a custody account per jurisdiction with a two-letter `state_code` (unique across all accounts); each new account starts with a `custody_balance_cents` of zero. Owners are registered with their `full_name`, the last four digits of their tax identifier in `ssn_last4` (exactly four digits, used for identity matching), the two-letter `address_state` of their current address, and a contact `email`; a new owner's `id_verified` flag begins as false. Recovery firms are registered with their `legal_name`, the two-letter `registered_state` in which they are licensed, their state-issued `license_number`, and their own contractual fee ceiling in `max_fee_pct` — a fraction strictly greater than 0 and at most 1.

### 3.2. Recording Property and Starting the Dormancy Clock

A `Holder` records each piece of apparently abandoned property it holds. The submission carries the `holder_id` of the reporting institution, the `property_type_id` of the category it falls under, the apparent `owner_name` as the holder recorded it, the face principal in `amount_cents` (a whole number of at least 0 cents, before any interest), and the `last_activity_date` of the owner's last self-initiated activity. Two fields are optional: `owner_last_known_state`, the two-letter state of the owner's last known address (absent or empty when unknown), and `issue_date`, the instrument's issuance date. A new property is created in `status` `ACTIVE`.

At creation the system computes two derived fields. It fixes the property's `escheat_state` by the priority rule of Section 2.7. It also computes the property's `dormancy_date` — the instant at which the property first becomes eligible to be declared dormant — from the governing property type. The anchor for that computation depends on the type's `dormancy_basis`: when the basis is `LAST_ACTIVITY`, the anchor is the property's `last_activity_date`; when the basis is `ISSUANCE`, the anchor is the property's `issue_date` (which must therefore be present for issuance-based types). The dormancy date is that anchor advanced forward by exactly the number of calendar years in the type's `dormancy_period_years`. Note that for one and the same property carrying both dates, the issuance basis and the last-activity basis generally yield different dormancy dates, because they start from different anchors.

Once the logical clock reaches the dormancy date, a `Holder` may drive the property from `ACTIVE` to `DORMANT`. The transition succeeds only when the current logical-clock instant is at or after the property's `dormancy_date`; the boundary is inclusive, so a property is dormant exactly at its dormancy date. Attempting the transition before that instant is rejected with `ERR_NOT_YET_DORMANT` (HTTP 409), and this dormancy-evaluation action is defined only from the `ACTIVE` state.

Properties can be listed and filtered by their holder, their property type, their attached report, their `status`, and their `escheat_state`, and a single property can be fetched by its identifier.

### 3.3. Due-Diligence Outreach and Owner Reactivation

For property whose type requires it, the holder must attempt to reach the owner before surrendering the property to the state. Sending a due-diligence notice against a `DORMANT` property advances it from `DORMANT` to `DUE_DILIGENCE` and creates a `DueDiligenceNotice` recording the `property_id` it concerns and the outreach channel in `method`, which is either `MAIL` or `EMAIL`; the notice's `sent_at` is stamped with the current logical-clock instant and its `responded` flag starts false with a null `responded_at`. Sending a notice is permitted only when the governing property type's `due_diligence_required` is true.

A holder may send follow-up notices. A second notice against a property already in `DUE_DILIGENCE` creates an additional `DueDiligenceNotice` but leaves the property in `DUE_DILIGENCE` (a self-transition that does not change status). Whether it is the first notice or a follow-up, the same spacing rule applies: a new notice may not be sent within `DUE_DILIGENCE_NOTICE_BUFFER_DAYS` — that is, within 30 days — of an existing notice on the same property. A notice that falls inside that 30-day window is rejected with `ERR_NOTICE_TOO_SOON` (HTTP 409).

If the owner responds to outreach, the holder records the response against the specific notice, provided that notice belongs to the property in question. Recording a response sets the notice's `responded` to true and its `responded_at` to the current logical-clock instant, and it reactivates the property by returning it from `DUE_DILIGENCE` to `ACTIVE` — the owner has effectively reclaimed the property, which leaves the escheat pipeline. The notices attached to a property can be listed for review.

### 3.4. Holder Reports: Drafting, Attaching, and Submitting

Property is surrendered to a jurisdiction through an annual **holder report**. A `Holder` opens a report by supplying the filing `holder_id`, the two-letter jurisdiction it is filed with in `report_state`, and the calendar year it covers in `report_period_year` (a whole number of at least 2000). A new report is created in `status` `DRAFT` with a `property_count` of zero, a `total_remitted_cents` of zero, and a null `submitted_at`. At most one report may exist for a given combination of holder, jurisdiction, and year; a duplicate is rejected with `ERR_REPORT_PERIOD_OVERLAP` (HTTP 409). Reports can be fetched individually and listed or filtered by holder, `report_state`, and `status`.

Properties are attached to a `DRAFT` report one at a time. An attach request names the `property_id` to add and carries `expected_report_version` for the optimistic-concurrency guard of Section 2.9. A property is eligible to attach when it is either `DORMANT` (for a property type whose `due_diligence_required` is false, giving a direct reporting path that skips outreach) or `DUE_DILIGENCE` (for a type that required outreach). In both cases three further conditions must hold: the property's `escheat_state` must equal the report's `report_state` (else `ERR_ESCHEAT_STATE_MISMATCH`, HTTP 422, per Section 2.7), the report must still be in `DRAFT`, and the property's `holder_id` must match the report's `holder_id`. A successful attach transitions the property to `REPORTED`, sets its `report_id` to the report, increments the report's `version` by one, and recomputes the report's `property_count` and `total_remitted_cents`.

A report's `total_remitted_cents` is defined as the sum, over every property currently attached to it (every property whose `report_id` equals the report), of that property's remittance amount **rounded to whole cents first, then summed**. Each property's remittance is rounded to cents individually before the summation; the total is never formed by summing raw un-rounded remittances and rounding once at the end, because the two can differ by a cent. The report's `property_count` is simply the number of properties currently attached.

Submitting a report moves it from `DRAFT` to `SUBMITTED` and stamps `submitted_at` with the current logical-clock instant. The submit request carries `declared_total_cents`, the holder's own reconciled figure. Three conditions gate submission. First, the filing holder's `audit_hold` must be false; a report submitted while the holder is under audit is rejected with `ERR_HOLDER_UNDER_AUDIT` (HTTP 409). Second, for every attached property whose type requires due diligence, the elapsed time from that property's earliest due-diligence notice `sent_at` to the current logical clock, measured in days, must be at least the property type's `due_diligence_min_days`; if any such property has not completed its waiting window, submission is rejected with `ERR_DUE_DILIGENCE_INCOMPLETE` (HTTP 422). Third, the submitted `declared_total_cents` must equal the report's computed `total_remitted_cents`; a mismatch is rejected with `ERR_REMITTANCE_MISMATCH` (HTTP 422).

### 3.5. Examination, Acceptance, and Escheat to Custody

A submitted report enters state review. A `StateExaminer` begins review of a `SUBMITTED` report, moving it to `UNDER_AUDIT`. From `UNDER_AUDIT`, the examiner either rejects the report — moving it to `REJECTED` — or accepts it. A `REJECTED` report is not terminal: the holder may return it from `REJECTED` to `DRAFT` to correct and refile it, forming a revise loop. Acceptance moves the report to `ACCEPTED`, which is terminal, and triggers the central escheat cascade.

When a report is accepted, every attached property still in `REPORTED` transitions to `ESCHEATED`. For each such property the system computes its `remitted_amount_cents` — principal plus accrued statutory interest — as follows. The number of whole calendar years the property has been dormant is the count of full calendar years between its `dormancy_date` and the current logical clock, rounded down. If the governing property type's `interest_bearing` flag is false, the interest is zero. Otherwise the raw interest is the property's face `amount_cents` multiplied by the annual statutory rate of 2 percent (`ANNUAL_INTEREST_RATE`, 0.02) multiplied by the number of whole dormant years; this raw interest is then capped so that it never exceeds one-half of the face principal (the cap is `amount_cents` times `MAX_INTEREST_MULTIPLE`, 0.5), and the applied interest is the smaller of the raw interest and that cap. The property's `remitted_amount_cents` is the face principal plus the applied interest, rounded half-up to whole cents.

Each escheated property produces a custody credit: the system writes a `REMIT_IN` `LedgerEntry` for that property's `remitted_amount_cents` against the custody account whose `state_code` is the property's `escheat_state` (recording the originating `property_id` and the `ref_report_id`), then recomputes that account's `custody_balance_cents`, which rises by the remitted amount. Because a single acceptance can escheat many properties, this is a depth-three chain from the report, through each property, to the ledger entries and the account balance — all applied together as described in Section 2.8.

### 3.6. Filing Claims and Working the Evidence Loop

Once property sits in state custody, an owner may reclaim it. A claim may be filed only against a `Property` in `ESCHEATED`; filing against a property in any other status is rejected with `ERR_PROPERTY_NOT_CLAIMABLE` (HTTP 409). A claim is filed either by the owner directly or by a licensed firm on the owner's behalf. The filing carries the `property_id` being claimed, the `claimant_owner_id` asserting ownership, and `filed_by`, which is either `OWNER` or `FIRM`. When `filed_by` is `FIRM`, the request must supply a non-null `recovery_firm_id` and an agreed fee fraction in `contract_fee_pct`; when `filed_by` is `OWNER`, the `recovery_firm_id` must be null and `contract_fee_pct` must be zero. A filing that violates this shape — a firm-filed claim without a firm, or an owner-filed claim carrying a firm or a nonzero fee — is rejected with `ERR_FIRM_REQUIRED` (HTTP 422).

The agreed `contract_fee_pct` is also capped. It may not exceed the smaller of the filing firm's own `max_fee_pct` and the statutory ceiling of 10 percent (`STATE_MAX_FEE_PCT`, 0.10); a fee exactly at that combined cap is allowed, and anything above it is rejected with `ERR_FEE_EXCEEDS_CAP` (HTTP 422). A property may carry at most one live claim at a time: if the property already has a claim in any non-terminal status — `FILED`, `UNDER_REVIEW`, `NEEDS_EVIDENCE`, `APPROVED`, or `PAID` — a new filing is rejected with `ERR_CLAIM_ALREADY_ACTIVE` (HTTP 409).

A new claim is created in `status` `FILED` with a null `examiner_user_id` and `approver_user_id`. At filing the system snapshots the claim's gross value in `claim_amount_cents` from the property's `remitted_amount_cents` at that moment, and it computes a `provisional_fee_cents` estimate. The provisional fee uses the property's pre-interest face value: it is the effective fee fraction — the smaller of the claim's `contract_fee_pct` and the 10-percent statutory ceiling — multiplied by the property's face `amount_cents`, rounded half-up to whole cents. (For an owner-filed claim the fee fraction is zero, so the provisional fee is zero.) Claims can be fetched individually and listed or filtered by their property, their `claimant_owner_id`, their `recovery_firm_id`, and their `status`.

Adjudication begins when a `StateExaminer` takes up a `FILED` claim, which records that examiner's `X-User-ID` as the claim's `examiner_user_id` and advances the claim from `FILED` to `UNDER_REVIEW`. From `UNDER_REVIEW` an examiner may request more evidence, moving the claim from `UNDER_REVIEW` to `NEEDS_EVIDENCE`. While a claim is being worked, the owner or recovery agent may upload supporting documents; each `EvidenceDocument` records the `claim_id` it supports and a `doc_type` that is one of `GOV_ID`, `PROOF_OF_ADDRESS`, `DEATH_CERTIFICATE`, or `OWNERSHIP_PROOF`, and is created in `status` `PENDING` with a null `reviewed_by_user_id`. A `StateExaminer` reviews a document by supplying a `decision` of either `ACCEPTED` or `REJECTED`, which sets the document's `status` accordingly and records the reviewing operator's `X-User-ID` as its `reviewed_by_user_id`. Evidence documents for a claim can be listed.

The claimant closes the loop by resubmitting a claim that is in `NEEDS_EVIDENCE`, which returns it from `NEEDS_EVIDENCE` to `UNDER_REVIEW`. Resubmission is permitted only when at least one `EvidenceDocument` for that claim has reached `status` `ACCEPTED`. This evidence loop — `UNDER_REVIEW` to `NEEDS_EVIDENCE` and back to `UNDER_REVIEW` — may repeat as many times as the examiner requires.

### 3.7. Approval and the Payout Waterfall

A claim that has been worked to satisfaction is adjudicated by a `StateApprover`, who either approves it or, acting as examiner, denies it. Denial is an examiner action from `UNDER_REVIEW` that moves the claim to `DENIED`, a terminal state. Approval moves a claim from `UNDER_REVIEW` to `APPROVED` and is gated by three conditions beyond the state check. The approving operator's `X-User-ID` must differ from the claim's recorded `examiner_user_id`, or the request is rejected with `ERR_SOD_VIOLATION` (HTTP 403) per Section 2.10. The property the claim references must be in `ESCHEATED`. And no `EvidenceDocument` for the claim may still be in `PENDING` — every uploaded document must have been reviewed to either `ACCEPTED` or `REJECTED` — otherwise approval is rejected with `ERR_EVIDENCE_REQUIRED` (HTTP 422). On success the approver's `X-User-ID` is recorded as the claim's `approver_user_id`.

Approval runs the **payout waterfall**, which fixes the claim's `fee_cents`, `admin_deduction_cents`, and `net_payout_cents` in a strict, pinned order, rounding half-up to whole cents at each step. The final recovery fee, unlike the provisional estimate, is computed on the escheated gross rather than the pre-interest face value. Step one sets `fee_cents` to the effective fee fraction — the smaller of the claim's `contract_fee_pct` and the 10-percent statutory ceiling (`STATE_MAX_FEE_PCT`, 0.10) — multiplied by the claim's `claim_amount_cents`, rounded half-up. Because `claim_amount_cents` equals the remitted principal plus accrued interest, for an interest-bearing property this final fee exceeds the provisional fee computed at filing. Step two forms the post-fee residual by subtracting `fee_cents` from `claim_amount_cents`. Step three sets the state administrative deduction, `admin_deduction_cents`, from a tier keyed on that post-fee residual: if the residual is at or below the administrative tier threshold of 100000 cents (`ADMIN_TIER_THRESHOLD_CENTS`), the deduction is a flat 500 cents (`ADMIN_FLAT_FEE_CENTS`); otherwise the deduction is 0.5 percent of the post-fee residual (`ADMIN_PCT`, 0.005), rounded half-up. Step four sets `net_payout_cents` to `claim_amount_cents` minus `fee_cents` minus `admin_deduction_cents`. These four amounts always satisfy the identity that the gross `claim_amount_cents` equals the sum of `fee_cents`, `admin_deduction_cents`, and `net_payout_cents`.

### 3.8. Payment, Property Settlement, and Compensating Void

Paying an `APPROVED` claim is a second `StateApprover` action and is again subject to segregation of duties: the paying operator's `X-User-ID` must differ from the claim's `examiner_user_id`, or the payment is rejected with `ERR_SOD_VIOLATION` (HTTP 403). Payment moves the claim from `APPROVED` to `PAID` and cascades to the underlying property, advancing it from `ESCHEATED` to `CLAIMED`. The cascade writes two debit entries against the custody account whose `state_code` is the property's `escheat_state`: a `PAYOUT_OUT` `LedgerEntry` for the claim's `net_payout_cents` and a `FEE_OUT` `LedgerEntry` for the claim's `fee_cents` (both recording the originating `property_id` and `ref_claim_id`). The account's `custody_balance_cents` is then recomputed and falls by the sum of the net payout and the fee.

A payment can be undone. Voiding a `PAID` claim moves it from `PAID` to `VOIDED`, a terminal state, and compensates the earlier disbursement. The void cascades the property back from `CLAIMED` to `ESCHEATED` and writes a single `CLAWBACK_IN` `LedgerEntry` for the full amount that had left custody — the sum of the claim's `net_payout_cents` and `fee_cents` — against the same jurisdiction's custody account (recording the `property_id` and `ref_claim_id`); the account's `custody_balance_cents` is recomputed and rises by that same sum. In keeping with the custody-conservation invariant of Section 2.8, the clawback exactly restores the balance that the payment had removed, and because the property returns to `ESCHEATED` it may be claimed afresh.

### 3.9. Holder Audits and Penalties

Independently of any single report, a `StateExaminer` may open an audit case against a holder to examine its compliance. Opening a case records the examining operator's `X-User-ID` as the case's `examiner_user_id`, names the holder under examination via `holder_id`, and creates the `AuditCase` in `status` `OPEN`. Opening a case also sets the holder's `audit_hold` to true. A holder's `audit_hold` is true whenever at least one of its audit cases is in a non-terminal state — that is, `OPEN` or `INFO_REQUESTED` — and, per Section 3.4, a true `audit_hold` blocks that holder from submitting reports. Audit cases can be fetched individually and listed or filtered by `holder_id` and `status`.

During an audit the examiner may request information from the holder, moving the case from `OPEN` to `INFO_REQUESTED`; the holder responds by providing the requested information, returning the case from `INFO_REQUESTED` to `OPEN`. This information loop may repeat. An audit case is closed in one of two terminal ways, both from `OPEN`. A clean close moves the case to `CLOSED_NO_FINDING` and, because that case is no longer non-terminal, recomputes the holder's `audit_hold` (which becomes false once no other case for the holder remains `OPEN` or `INFO_REQUESTED`). An assessed close records an audit finding: it carries an `assessed_penalty_cents` amount, which must be at least 1, and free-text `findings`, moves the case to `CLOSED_ASSESSED`, adds the case's `assessed_penalty_cents` to the holder's running `assessed_penalty_cents` total, sets the holder's `status` to `SUSPENDED`, and likewise recomputes the holder's `audit_hold`.

Every movement of value in the system is auditable through the custody ledger. Individual ledger entries can be fetched by identifier, and the ledger can be listed or filtered by `state_account_id`, by originating `property_id`, by `ref_claim_id`, and by `ref_report_id`, so that a reviewer can trace exactly which remittances, payouts, fees, and clawbacks make up any jurisdiction's `custody_balance_cents`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify or transition an existing resource, including state-machine actions and the logical-clock control, return a `200 OK` status code. The complete request bodies, side effects, and validation rules for each endpoint are specified in the narratives of Section 3; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/holders` | Register a holder institution | StateAdmin |
| GET | `/holders/{id}` | Fetch a holder | StateAdmin, Holder, StateExaminer, StateApprover |
| POST | `/property-types` | Define a property category and its dormancy/interest rules | StateAdmin |
| GET | `/property-types/{id}` | Fetch a property type | StateAdmin, Holder, StateExaminer, StateApprover |
| POST | `/state-accounts` | Open a custody account for a jurisdiction | StateAdmin |
| GET | `/state-accounts/{id}` | Fetch a custody account with its computed balance | StateAdmin, StateExaminer, StateApprover |
| POST | `/owners` | Register an owner / claimant identity | StateAdmin |
| GET | `/owners/{id}` | Fetch an owner | StateAdmin, Owner, StateExaminer, StateApprover |
| POST | `/recovery-firms` | Register a recovery / locator firm | StateAdmin |
| GET | `/recovery-firms/{id}` | Fetch a recovery firm | StateAdmin, RecoveryAgent, StateExaminer, StateApprover |
| POST | `/properties` | Record a property; computes escheat_state and dormancy_date | Holder |
| GET | `/properties/{id}` | Fetch a property | StateAdmin, Holder, StateExaminer, StateApprover, Owner, RecoveryAgent |
| GET | `/properties` | List/filter properties | StateAdmin, Holder, StateExaminer, StateApprover |
| POST | `/properties/{id}/evaluate-dormancy` | Attempt ACTIVE to DORMANT once the dormancy date is reached | Holder |
| POST | `/properties/{id}/notices` | Send a due-diligence notice; moves DORMANT to DUE_DILIGENCE | Holder |
| GET | `/properties/{id}/notices` | List due-diligence notices for a property | StateAdmin, Holder, StateExaminer |
| POST | `/due-diligence-notices/{id}/record-response` | Record an owner response; reactivates the property | Holder |
| POST | `/reports` | Open a DRAFT holder report for a jurisdiction and period | Holder |
| GET | `/reports/{id}` | Fetch a holder report with computed totals | StateAdmin, Holder, StateExaminer, StateApprover |
| GET | `/reports` | List/filter holder reports | StateAdmin, Holder, StateExaminer, StateApprover |
| POST | `/reports/{id}/add-property` | Attach a property to a DRAFT report (OCC on report version) | Holder |
| POST | `/reports/{id}/submit` | Submit a DRAFT report; requires reconciled total and no audit hold | Holder |
| POST | `/reports/{id}/begin-review` | Move a SUBMITTED report to UNDER_AUDIT | StateExaminer |
| POST | `/reports/{id}/accept` | Accept a report; escheats attached properties and credits custody | StateExaminer |
| POST | `/reports/{id}/reject` | Reject a report under audit | StateExaminer |
| POST | `/reports/{id}/revise` | Return a REJECTED report to DRAFT for correction | Holder |
| POST | `/claims` | File a claim against an ESCHEATED property | Owner, RecoveryAgent |
| GET | `/claims/{id}` | Fetch a claim | StateAdmin, StateExaminer, StateApprover, Owner, RecoveryAgent |
| GET | `/claims` | List/filter claims | StateAdmin, StateExaminer, StateApprover, Owner, RecoveryAgent |
| POST | `/claims/{id}/examine` | Examiner takes up a FILED claim | StateExaminer |
| POST | `/claims/{id}/request-evidence` | Request more evidence; UNDER_REVIEW to NEEDS_EVIDENCE | StateExaminer |
| POST | `/claims/{id}/evidence` | Upload an evidence document for a claim | Owner, RecoveryAgent |
| GET | `/claims/{id}/evidence` | List evidence documents for a claim | StateAdmin, StateExaminer, StateApprover, Owner, RecoveryAgent |
| POST | `/claims/{id}/evidence/{doc_id}/review` | Accept or reject an evidence document | StateExaminer |
| POST | `/claims/{id}/resubmit` | Resubmit after evidence; NEEDS_EVIDENCE to UNDER_REVIEW | Owner, RecoveryAgent |
| POST | `/claims/{id}/approve` | Approve an UNDER_REVIEW claim (SoD enforced); runs payout waterfall | StateApprover |
| POST | `/claims/{id}/pay` | Pay an APPROVED claim; settles property and debits custody | StateApprover |
| POST | `/claims/{id}/deny` | Deny an UNDER_REVIEW claim (terminal) | StateExaminer |
| POST | `/claims/{id}/void` | Void a PAID claim; compensating clawback restores custody | StateApprover |
| POST | `/audit-cases` | Open an audit case against a holder; sets audit_hold | StateExaminer |
| GET | `/audit-cases/{id}` | Fetch an audit case | StateAdmin, StateExaminer, Holder |
| GET | `/audit-cases` | List/filter audit cases | StateAdmin, StateExaminer, Holder |
| POST | `/audit-cases/{id}/request-info` | Request info from the holder; OPEN to INFO_REQUESTED | StateExaminer |
| POST | `/audit-cases/{id}/provide-info` | Holder provides requested info; INFO_REQUESTED to OPEN | Holder |
| POST | `/audit-cases/{id}/close-clean` | Close an audit with no finding; may clear audit_hold | StateExaminer |
| POST | `/audit-cases/{id}/close-assess` | Close an audit with an assessed penalty; may clear audit_hold | StateExaminer |
| GET | `/ledger-entries/{id}` | Fetch a single ledger entry | StateAdmin, StateExaminer, StateApprover |
| GET | `/ledger-entries` | List/filter ledger entries | StateAdmin, StateExaminer, StateApprover |
| POST | `/_clock/set_current_utc` | Set the server logical clock | StateAdmin |

## 5. Error Code Catalogue

The trigger conditions for each error are described in the Section 2 and Section 3 narratives that govern the operations they guard; this catalogue lists only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_HOLDER_NOT_FOUND` | 404 Not Found |
| `ERR_PROPERTY_TYPE_NOT_FOUND` | 404 Not Found |
| `ERR_STATE_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_OWNER_NOT_FOUND` | 404 Not Found |
| `ERR_FIRM_NOT_FOUND` | 404 Not Found |
| `ERR_PROPERTY_NOT_FOUND` | 404 Not Found |
| `ERR_NOTICE_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_EVIDENCE_NOT_FOUND` | 404 Not Found |
| `ERR_AUDIT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_NOT_YET_DORMANT` | 409 Conflict |
| `ERR_PROPERTY_NOT_CLAIMABLE` | 409 Conflict |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_HOLDER_UNDER_AUDIT` | 409 Conflict |
| `ERR_DUE_DILIGENCE_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_NOTICE_TOO_SOON` | 409 Conflict |
| `ERR_ESCHEAT_STATE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_FIRM_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CLAIM_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_REPORT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_EVIDENCE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_STALE_REPORT_VERSION` | 412 Precondition Failed |
| `ERR_FEE_EXCEEDS_CAP` | 422 Unprocessable Entity |
| `ERR_REMITTANCE_MISMATCH` | 422 Unprocessable Entity |
