# Deed-in-Lieu & Cash-for-Keys Administration API — Product Requirements Document

## 1. Introduction

Mortgage servicers working with delinquent borrowers need orderly alternatives to foreclosure, and the two workhorses of that toolkit are the deed-in-lieu — where the borrower conveys title voluntarily in exchange for relocation assistance and a waiver of the remaining debt — and cash-for-keys — where the borrower simply vacates on an agreed date, in an agreed condition, in exchange for assistance money. This document specifies the Deed-in-Lieu & Cash-for-Keys Administration API, the system of record for a servicer's property solutions team as it shepherds each workout from first eligibility review to a recorded deed or a paid-out set of keys.

The API covers the full administrative arc: eligibility evaluation and the marketing-period requirement; title condition and junior-lien clearance; negotiation of the relocation-assistance amount against a condition-of-property standard; the vacate-date agreement and the inspection performed at handover; disbursement of funds upon key delivery and broom-clean verification, under treasury segregation of duties; deficiency-waiver documentation; deed recording and the servicing-system update that follows; and, when an occupant refuses to leave, holdover escalation into the eviction docket. All resources are mounted under a single top-level path, `/property-solutions`, and every temporal rule in the system is evaluated against a deterministic logical clock rather than wall-clock time, so that outcomes are reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which that user acts. The system recognizes exactly eight roles: `ServicingAdmin`, `PropertySolutionsSpecialist`, `WorkoutManager`, `TitleOfficer`, `Borrower`, `Inspector`, `DisbursementOfficer`, and `LegalCounsel`. A request that omits either header, or that names a role outside this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not among the roles authorized for the endpoint, or that fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403).

Seven of the eight roles are opaque operator identities. When `X-User-Role` is `ServicingAdmin`, `PropertySolutionsSpecialist`, `WorkoutManager`, `TitleOfficer`, `Inspector`, `DisbursementOfficer`, or `LegalCounsel`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `assigned_specialist_id` on a workout case, as `created_by_specialist_id` on an agreement, or as `requested_by_user_id`, `approved_by_user_id`, and `released_by_user_id` on a disbursement — but it never compares the header value to any entity's `id`. The `Inspector` role adds one convention: an inspector's `X-User-ID` is the same opaque identifier that appointments carry as `inspector_id`, and it must match that field when the inspector creates an inspection report, submits one, or records a no-access outcome.

The `Borrower` role is entity-backed. When `X-User-Role` is `Borrower`, `X-User-ID` is the `id` of the acting Borrower record; ownership checks on any resource that references a Borrower compare the resource's borrower field to `X-User-ID`. A borrower may counter or accept an agreement only when the header equals the parent case's `borrower_id`, may withdraw only a case whose `borrower_id` matches the header, may read only their own borrower record, and may read only their own cases and those cases' sub-resources. Two read endpoints are exempt from this ownership check: `GET /property-solutions/listings/{id}` and `GET /property-solutions/listings/{id}/suspensions` perform no borrower-ownership check, so a borrower may read any listing and its suspensions.

Role charters in brief: the `ServicingAdmin` boards loans, borrowers, and properties and operates the logical clock. The `PropertySolutionsSpecialist` owns the case pipeline from intake through the disbursement request. The `WorkoutManager` supervises — granting marketing exceptions, escalating holdovers, terminating agreements, rescinding waivers, and clawing back disbursements. The `TitleOfficer` manages title commitments, junior liens, and lien releases. The `DisbursementOfficer` approves and releases funds under segregation of duties. The `LegalCounsel` documents deficiency waivers, runs deed recordings, and conducts the eviction docket.

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

List endpoints paginate through two query parameters: `limit` — the maximum number of items to return, defaulting to 10, with a minimum of 1 and a maximum of 100 — and `offset` — the number of items to skip, defaulting to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope. Several lists additionally accept filters: the loans list and the junior-liens list accept `status`, the properties list accepts `loan_id`, and the cases list accepts `loan_id`, `borrower_id`, and `status`. A `limit` or `offset` that is non-integer or outside its bounds is rejected with `ERR_INVALID_REQUEST`. In the `meta` of a paginated response, `total_count` counts every resource matching the supplied filters (not just the returned page), and `has_more` is true exactly when `offset` + `limit` is less than `total_count`. Filter values are matched literally against the named field; an unrecognized filter value simply yields an empty page.

### 2.4. The Logical Clock

Every temporal rule in this document — offer expiry, the vacate-notice minimum, inspection scheduling notice, holdover grace periods, the recording deadline, creditable marketing days — is evaluated against a server-maintained logical clock, never against wall-clock time. Before any explicit adjustment the clock reads exactly 2026-08-01T00:00:00Z, and the server never falls back to wall-clock time. A `ServicingAdmin`-only test-driving capability, `POST /_clock/set_current_utc`, sets the clock to a supplied `to_iso8601` instant — which may lie earlier or later than the current reading — and answers 200 with the resulting `current_utc`. Advancing the clock moves the basis on which creditable marketing days and offer expiry are evaluated, but it performs no eager sweep: an `OFFERED` agreement whose `offer_expires_at` has passed flips to `EXPIRED` lazily — when the agreement is next read or acted upon — not at the moment the clock is set.

### 2.5. Common Resource Properties

All fifteen resources — Loan, Borrower, Property, WorkoutCase, MarketingListing, ListingSuspension, TitleCommitment, JuniorLien, SettlementAgreement, InspectionAppointment, InspectionReport, Disbursement, DeficiencyWaiver, DeedRecording, and EvictionCase — share four system-managed fields. The `id` is a server-minted UUID carrying no type prefix. The `created_at` timestamp records when the resource was first created, and `updated_at` refreshes upon any change to the resource's properties; both are ISO 8601 UTC timestamps with three fractional digits. The `version` is a system-managed integer that starts at 1 on creation and increments by one with every modification to the resource. All server-generated timestamps — `created_at`, `updated_at`, the envelope's `api_request_timestamp`, and every action stamp such as `released_at`, `filed_at`, `recorded_at`, `accepted_at`, `closed_at`, or a suspension's `started_at`/`ended_at` — are read from the logical clock of §2.4, never from wall-clock time. When a single operation cascades across several resources, each mutated resource independently has its `updated_at` refreshed and its `version` incremented.

### 2.6. Monetary Precision and Rounding

All monetary amounts in the system are represented as integer cents. Wherever a calculation prescribes rounding, the method is round half up to whole cents, and rounding occurs only at the prescribed steps: the per-diem interest derivation on the loan, the occupancy-multiplier step of the assistance quote, each individual line item of the condition-deduction schedule (before any summation), and the holdover penalty cap. Day arithmetic — delinquency, marketing spans, grace periods, deadlines — is performed in whole days on ISO calendar dates.

### 2.7. Optimistic Concurrency Control

Two write endpoints guard against stale parent versions. Creating a settlement agreement through `POST /property-solutions/cases/{id}/agreements` requires a non-optional `expected_case_version` input carrying the client's last observed `version` of the parent workout case; if that value does not match the case's current `version` — because another writer has advanced the case since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Releasing a junior lien through `POST /property-solutions/title-commitments/{id}/lien-releases` likewise requires a non-optional `expected_title_commitment_version` matching the title commitment's current `version`; a mismatch is rejected with `ERR_STALE_TITLE_VERSION` (HTTP 412). On both guarded endpoints the version match is evaluated after the state and uniqueness checks of §2.10 and before the temporal and fiscal checks: for agreement creation it follows the one-active-agreement rule and precedes the vacate-notice check, and for a lien release it follows the lien state check and precedes the settlement ceiling. Endpoints not named here do not accept a version field; a version field supplied to them is ignored.

### 2.8. Hierarchical Consistency and Cascading State Propagation

State changes rarely stay on one resource. When a child resource reaches a state that settles its parent's readiness — the last junior lien released on a title commitment, a handover report submitted, a deed recording confirmed, an eviction filed — the server advances the parent automatically, without an explicit client request on that parent, and each such reconciliation mutates every touched resource's `updated_at` and `version`. The same principle runs in reverse for teardown: withdrawing a case resolves every dependent agreement, listing, and disbursement into its appropriate terminal state so that no orphaned in-flight work survives. These cascades are specified per workflow in §3; the guarantee here is that each hop of a cascade is atomic with the triggering write and is reflected in the version counters of every entity the cascade touches.

### 2.9. Nested Resource Retrieval and Identifier Resolution

Requests that target nested resources are validated left to right along the path: the first identifier that does not resolve to an existing resource determines the error, and deeper identifiers are never consulted. Each resource has its own not-found error — `ERR_LOAN_NOT_FOUND`, `ERR_BORROWER_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TITLE_COMMITMENT_NOT_FOUND`, `ERR_LIEN_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_RECORDING_NOT_FOUND`, and `ERR_EVICTION_CASE_NOT_FOUND`, each HTTP 404. The same resolution duty applies to foreign-key references inside request payloads — `loan_id`, `borrower_id`, `case_id`, `agreement_id`, and `lien_id` must each resolve, and a `lien_id` in a lien-release payload must resolve on the addressed title commitment. Requests that reach no defined route are rejected with `ERR_INVALID_REQUEST` (HTTP 404), and requests using an unsupported method on a defined route are rejected with `ERR_INVALID_REQUEST` (HTTP 405).

### 2.10. Validation Order and Error Priority

Every request is validated against an ordered ladder, and the first failing rung determines the error response. First, authentication: the headers are present and the role is declared, failing which the request is rejected with `ERR_UNAUTHENTICATED`. Second, role authorization: the acting role appears in the endpoint's authorized set, failing which the request is rejected with `ERR_FORBIDDEN`. Entity-backed ownership checks — a Borrower's `X-User-ID` must equal the parent case's `borrower_id` to counter or accept an agreement, and an Inspector's `X-User-ID` must equal the appointment's `inspector_id` to create or submit a report or record a no-access — are evaluated only after the path identifiers have resolved (existence, rung three), and, where §3 pins a guard order for a specific action, at the position §3 pins: on agreement counter and accept the state check precedes the ownership check, and on the inspector actions (create report, submit report, record no-access) the appointment or report state check precedes the identity check; on all other endpoints an ownership failure surfaces as `ERR_FORBIDDEN` immediately after existence resolution. Third, existence: path identifiers resolve left to right and payload references resolve, per §2.9. Fourth, well-formedness: required fields are present, types are valid, enum values fall within their declared domains (an out-of-domain enum value is rejected with `ERR_INVALID_ENUM`, HTTP 400), integer cent fields respect their declared sign constraints, and datetimes are well formed; an empty string counts as absent for a required string field, and a request body that is not a JSON object is malformed; other malformations are rejected with `ERR_INVALID_REQUEST` (HTTP 400). Fifth, state: the target resource must be in a state from which the requested transition exists, and terminal states reject all actions; failures surface as the per-entity 409 errors — `ERR_CASE_INVALID_STATE`, `ERR_LOAN_INVALID_STATE`, `ERR_LISTING_INVALID_STATE`, `ERR_TITLE_INVALID_STATE`, `ERR_LIEN_INVALID_STATE`, `ERR_AGREEMENT_INVALID_STATE`, `ERR_APPOINTMENT_INVALID_STATE`, `ERR_REPORT_INVALID_STATE`, `ERR_DISBURSEMENT_INVALID_STATE`, `ERR_RECORDING_INVALID_STATE`, `ERR_EVICTION_INVALID_STATE`, and `ERR_WAIVER_INVALID_STATE`.

Business rules then apply in ascending priority. The segregation-of-duties checks on disbursement approval and release come first, followed by the uniqueness family — three members share a single priority level without ambiguity because they guard disjoint endpoints: `loan_number` uniqueness (reported as `ERR_INVALID_REQUEST`), the one-active-listing rule (`ERR_ACTIVE_LISTING_EXISTS`), and lien-position uniqueness (`ERR_LIEN_POSITION_DUPLICATE`) — together with the one-active-agreement rule (`ERR_ACTIVE_AGREEMENT_EXISTS`). Next come the negotiation-round cap (`ERR_NEGOTIATION_ROUND_LIMIT`), the inspector calendar-conflict rule (`ERR_INSPECTOR_SCHEDULE_CONFLICT`), and the eligibility gates (`ERR_ELIGIBILITY_CRITERIA_NOT_MET`). Temporal rules follow: offer expiry (`ERR_OFFER_EXPIRED`), the ten-day vacate notice (`ERR_VACATE_DATE_TOO_SOON`), the inspection-notice minimum (`ERR_INSPECTION_TOO_SOON`), the marketing minimum (`ERR_MARKETING_PERIOD_NOT_MET`), the holdover grace period (`ERR_HOLDOVER_GRACE_NOT_ELAPSED`), and the recording deadline (`ERR_RECORDING_DEADLINE_PASSED`). Referential gates come after: the existence of a listing (`ERR_LISTING_MISSING`) and of a title commitment (`ERR_TITLE_COMMITMENT_MISSING`), junior-lien clearance (`ERR_JUNIOR_LIENS_OUTSTANDING`), key return (`ERR_KEYS_NOT_RETURNED`), and waiver documentation (`ERR_WAIVER_NOT_DOCUMENTED`). The fiscal checks close the ladder: disbursement positivity (`ERR_DISBURSEMENT_NOT_POSITIVE`), the remaining-assistance ceiling (`ERR_DISBURSEMENT_EXCEEDS_REMAINING`), and the lien-settlement ceiling (`ERR_SETTLEMENT_EXCEEDS_LIEN`).

Several relative orders are pinned and worth stating outright. On inspection scheduling, the calendar-conflict rule is evaluated before the minimum-notice rule. On agreement acceptance, offer expiry is checked before junior-lien clearance — the temporal guard outranks the referential one. On marketing certification, the listing-existence check precedes the creditable-days assessment. On disbursement creation, the remaining-assistance ceiling is evaluated last, after the state check and the positivity check. On disbursement approval, the state check precedes the approver-differs-from-requester rule; on release, the state check comes first, then the releaser-differs-from-approver rule, then the key-return rule. On recording confirmation, the waiver-documentation gate (`ERR_WAIVER_NOT_DOCUMENTED`) is evaluated before the recording-deadline check (`ERR_RECORDING_DEADLINE_PASSED`).

### 2.11. Segregation of Duties in Fund Disbursement

Assistance money moves only under dual control. Each disbursement records the `X-User-ID` of the specialist who requested it as `requested_by_user_id`, of the officer who approved it as `approved_by_user_id`, and of the officer who released it as `released_by_user_id`. The `DisbursementOfficer` approving a disbursement must not be the person recorded as its requester; a match is rejected with `ERR_SOD_APPROVER_EQUALS_REQUESTER` (HTTP 422). The officer releasing an approved disbursement must not be the officer who approved it; a match is rejected with `ERR_SOD_RELEASER_EQUALS_APPROVER` (HTTP 422). These two rules are absolute — no role, not even a `WorkoutManager`, overrides them.

## 3. Business Logic & Workflows

### 3.1. Boarding Reference Data: Loans, Borrowers, and Properties

Before any workout can begin, a `ServicingAdmin` boards the reference data. Boarding a loan requires a `loan_number` (unique across all loans — a duplicate is refused with `ERR_INVALID_REQUEST`), an `unpaid_principal_balance_cents` that is strictly greater than zero, `accrued_interest_cents`, `escrow_advances_cents`, and `foreclosure_fees_cents` (each zero or greater), the `note_annual_rate` expressed as a decimal (greater than zero and at most 0.25), the `fair_market_value_cents` supported by a broker price opinion (zero or greater), and `delinquency_days` at boarding (zero or greater). The `foreclosure_referral_status` is one of `NONE`, `REFERRED`, `ACTIVE`, or `WITHDRAWN`, defaulting to `NONE` when omitted. From these inputs the system derives `per_diem_interest_cents` — the unpaid principal balance multiplied by the note annual rate and divided by 365, rounded half-up to whole cents — computed at creation and again on any balance or rate change; any client-supplied value for it is ignored. A freshly boarded loan has `status` `ACTIVE_DELINQUENT`, a `deficiency_balance_cents` of zero, and `servicing_system_synced` false.

Over its life a loan moves from `ACTIVE_DELINQUENT` to `WORKOUT_IN_PROGRESS` when a case is submitted, back to `ACTIVE_DELINQUENT` when that case is declined or withdrawn, onward to `DEED_IN_LIEU_COMPLETED` — its only terminal state — when a deed-in-lieu recording is confirmed or a cash-for-keys case finishes paying out (at which point `servicing_system_synced` flips to true and the deficiency balance reflects the executed waiver), and into `FORECLOSURE_PROCEEDING` if an eviction is filed on a deed-in-lieu case, returning to `WORKOUT_IN_PROGRESS` if that eviction is later dismissed because the occupant vacated.

Registering a borrower records the `full_name`, a free-form contact `email`, a `hardship_type` of `INVOLUNTARY_UNEMPLOYMENT`, `MEDICAL`, `DIVORCE`, or `NONE`, and a `self_reported_condition_grade` of `A`, `B`, `C`, or `D` — the borrower's own assessment of property condition, which later feeds the provisional assistance quote on the `SELF_REPORTED` basis; all four are required inputs. Registering the subject property ties it to its loan through the `loan_id` in the payload and records the `address_line`, the `county` of record (which later determines where the deed is recorded), a `state_code` (conventionally two letters, recorded as supplied with no format validation), an `occupancy_type` of `OWNER_OCCUPIED`, `TENANT_OCCUPIED`, or `SECOND_HOME`, and the `required_condition_standard` demanded at handover — currently only `BROOM_CLEAN` is supported, and it is the default. The `address_line`, `county`, `state_code`, and `occupancy_type` are required inputs. Several properties may be registered against the same loan; wherever the system consults a loan's property — the occupancy multiplier of the assistance quote — it reads the earliest-registered one.

### 3.2. Case Intake, Eligibility Evaluation, and Withdrawal

A `PropertySolutionsSpecialist` opens a workout case with a payload carrying the `loan_id`, the `borrower_id`, and the `program_type` — `DEED_IN_LIEU` or `CASH_FOR_KEYS`. The case is born in `INTAKE`, with the creating specialist's `X-User-ID` frozen into the immutable `assigned_specialist_id`. Opening a case performs no check on the loan's status and no uniqueness check against other cases of the same loan; the loan gate bites later, at submission. Across its life a case's `status` ranges over sixteen values — `INTAKE`, `ELIGIBILITY_REVIEW`, `MARKETING_PERIOD`, `TITLE_REVIEW`, `TERMS_NEGOTIATION`, `AGREEMENT_ACTIVE`, `VACATE_PENDING`, `HANDOVER_INSPECTION`, `DISBURSEMENT_PENDING`, `RECORDING_PENDING`, `COMPLETED`, `DECLINED`, `WITHDRAWN`, `HOLDOVER_ESCALATED`, `EVICTION_IN_PROGRESS`, and `CLOSED_EVICTED` — of which `COMPLETED`, `DECLINED`, `WITHDRAWN`, and `CLOSED_EVICTED` are terminal and reject every further action with `ERR_CASE_INVALID_STATE`.

Submitting the case moves it from `INTAKE` to `ELIGIBILITY_REVIEW`. The move is allowed only while the loan is `ACTIVE_DELINQUENT` — otherwise the submission is refused with `ERR_LOAN_INVALID_STATE` — and it flips the loan to `WORKOUT_IN_PROGRESS`, incrementing the `version` of both the case and the loan. Any case action attempted from the wrong state is refused with `ERR_CASE_INVALID_STATE`.

Eligibility evaluation takes a `decision` of `PASS` or `FAIL` plus optional `notes`. A `PASS` decision is gated on the loan's posture: the loan must be at least 31 days delinquent, and its foreclosure referral must not be `ACTIVE`; a `PASS` attempted against those gates fails with `ERR_ELIGIBILITY_CRITERIA_NOT_MET`. A passing evaluation advances the case to `MARKETING_PERIOD`. A failing one moves the case to `DECLINED` and returns the loan from `WORKOUT_IN_PROGRESS` to `ACTIVE_DELINQUENT`, again incrementing both versions.

During the marketing stage a `WorkoutManager` may grant a marketing-period exception, supplying a `reason`; the grant sets `marketing_exception_granted` to true and preserves the reason in `marketing_exception_reason`, incrementing the case's `version`.

Withdrawal — by the specialist, or by the borrower on their own case — is available from `INTAKE`, `ELIGIBILITY_REVIEW`, `MARKETING_PERIOD`, `TITLE_REVIEW`, `TERMS_NEGOTIATION`, `AGREEMENT_ACTIVE`, `VACATE_PENDING`, and `HOLDOVER_ESCALATED`, and is refused from `RECORDING_PENDING`, `EVICTION_IN_PROGRESS`, and every terminal state. Withdrawal is a deep cascade: any agreement of the case in `DRAFT`, `OFFERED`, `COUNTERED`, or `ACCEPTED` moves to `TERMINATED`; any listing in `ACTIVE` or `SUSPENDED` moves to `CLOSED`; any disbursement in `PENDING` or `APPROVED` moves to `VOIDED`; the loan falls back from `WORKOUT_IN_PROGRESS` to `ACTIVE_DELINQUENT`; and when the case had been in `HOLDOVER_ESCALATED`, any eviction case still `ESCALATED` is dismissed with `dismissal_reason` `OTHER`. The case's own `version` increments as well.

### 3.3. The Marketing Period and Creditable Days

While a case sits in `MARKETING_PERIOD`, the specialist lists the property: the payload carries the `case_id`, the `list_date` (which must not lie in the future relative to the logical clock — a future `list_date` is rejected with `ERR_INVALID_REQUEST` and, like the other input validations, is evaluated before the case-state check), and the `list_price_cents` (strictly greater than zero). Only one non-`CLOSED` listing may exist per case — attempting to create a second while one is `ACTIVE` or `SUSPENDED` is rejected with `ERR_ACTIVE_LISTING_EXISTS`. A listing is born `ACTIVE`, and its `creditable_days` are computed from that moment.

Suspending an `ACTIVE` listing moves it to `SUSPENDED` and opens a suspension interval — a ListingSuspension record whose `listing_id` points back at the listing, whose `started_at` is the current logical timestamp, whose `ended_at` stays null while the suspension is open, and whose `reason` comes from the suspend payload. Resuming moves the listing from `SUSPENDED` back to `ACTIVE` and closes the open suspension by stamping its `ended_at` with the current logical timestamp. Closing — whether from `ACTIVE` or from `SUSPENDED` — moves the listing to `CLOSED`, stamps `closed_at` with the current logical timestamp, closes any open suspension the same way, and freezes `creditable_days` at its closing value. Each of these three actions recomputes `creditable_days`, and each demands the matching source state: suspending anything but an `ACTIVE` listing, resuming anything but a `SUSPENDED` one, or acting on a `CLOSED` listing is refused with `ERR_LISTING_INVALID_STATE`.

Creditable days measure how long the property was genuinely on the market. For a listing that is not `CLOSED`, the evaluation date is the current logical date (and any read of the listing through its direct endpoint, `GET /property-solutions/listings/{id}`, recomputes the figure against that date; collection reads return the most recently computed stored value); for a `CLOSED` listing the evaluation date is the closing date, so the value stays frozen. The computation proceeds in a pinned order. First, the raw span is the number of whole days from `list_date` to the evaluation date, floored at zero. Second, every suspension interval — its endpoints taken as the calendar dates of its `started_at` and `ended_at` timestamps — is clamped to the window from `list_date` to the evaluation date, an open suspension — one whose `ended_at` is still null — is treated as ending on the evaluation date, and an interval left empty by clamping is dropped. Third, the clamped intervals are sorted by start date, ties broken by earlier `created_at` first, and merged into a union: scanning in that order, an interval merges into the running union interval whenever its start date falls on or before the day immediately following the running interval's current end date — so overlapping intervals and back-to-back intervals (one ending on a date, the next starting on the very next date, an adjacency gap of zero intervening days) coalesce — with the running end extending to the later of the two end dates. Fourth, suspended days are the sum of the merged union's interval lengths in whole days. Finally, `creditable_days` is the span minus the suspended days, floored at zero. Naively subtracting each suspension interval independently double-counts overlapping suspensions and must not be used.

Certifying the marketing period is the gate from `MARKETING_PERIOD` to `TITLE_REVIEW`, and its checks run in a fixed order. The case must be in `MARKETING_PERIOD` (`ERR_CASE_INVALID_STATE` otherwise). At least one listing must exist for the case — certification with none is rejected with `ERR_LISTING_MISSING`. Then the marketing minimum applies: the most recently created listing must show at least 90 creditable days, unless a marketing exception has been granted on the case; failing both alternatives yields `ERR_MARKETING_PERIOD_NOT_MET`. A successful certification advances the case to `TITLE_REVIEW` and increments its `version`.

### 3.4. Title Clearance: Commitments, Junior Liens, and Releases

Once a case reaches `TITLE_REVIEW`, a `TitleOfficer` orders a title commitment by supplying the `case_id` — ordering against a case in any other state is refused with `ERR_CASE_INVALID_STATE` — and the commitment is born `ORDERED`. A case may carry several commitments over its life; there is no uniqueness gate. Recording receipt of the commitment — with the `vested_owner_name` as it appears on title — moves it from `ORDERED` to `RECEIVED` (any other source state draws `ERR_TITLE_INVALID_STATE`) and increments its `version`; when the commitment shows no unreleased liens at that moment, it immediately bubbles up from `RECEIVED` to `CLEARED` in the same operation. A commitment's `unreleased_lien_count` is the count of its junior liens still in `UNRELEASED` status.

Junior liens are recorded against a commitment that is `RECEIVED` or `CLEARED`; attempting to add one to an `ORDERED` commitment is rejected with `ERR_TITLE_INVALID_STATE`. Each lien carries a `title_commitment_id` tying it back to the commitment on which it appears, and each takes a `lienholder_name`, an `amount_cents` strictly greater than zero, and a `position` that must be at least 2 (position 1 belongs to the senior lien) and unique within the commitment — a duplicate position is refused with `ERR_LIEN_POSITION_DUPLICATE`. The new lien is born `UNRELEASED`, the commitment's `unreleased_lien_count` rises by one, and the commitment's `version` increments; adding a lien to a `CLEARED` commitment — supplemental title work turning up a newly discovered lien — reopens it, reverting it from `CLEARED` to `RECEIVED`.

Releasing a lien is the OCC-guarded write of §2.7: the payload names the `lien_id`, the agreed `settlement_amount_cents`, and the `expected_title_commitment_version`. The lien must be `UNRELEASED` (`ERR_LIEN_INVALID_STATE` otherwise), and the settlement must not exceed the lien's own `amount_cents` — a settlement that does is rejected with `ERR_SETTLEMENT_EXCEEDS_LIEN`. A successful release stamps the lien's `settlement_amount_cents` and `released_at`, moves it to its terminal `RELEASED` state, decrements the commitment's `unreleased_lien_count` by one, and increments the commitment's `version`; when that count reaches zero, the commitment bubbles up from `RECEIVED` to `CLEARED` with another version increment. A successful release answers 200 with the updated lien.

Certifying title moves the case from `TITLE_REVIEW` to `TERMS_NEGOTIATION` and increments the case's `version`. A title commitment must exist for the case (`ERR_TITLE_COMMITMENT_MISSING` otherwise), and the case's most recently created commitment must be `CLEARED`: that commitment still `ORDERED` — not yet received, with zero liens recorded — is rejected with `ERR_TITLE_INVALID_STATE`, while it still carrying an `UNRELEASED` junior lien is rejected with `ERR_JUNIOR_LIENS_OUTSTANDING`.

### 3.5. Negotiating the Settlement Agreement

With title cleared, the specialist drafts a settlement agreement against the case — the case must be in `TERMS_NEGOTIATION` — supplying the agreed `vacate_date` and the `expected_case_version` required by §2.7. The vacate date must fall at least ten days after the current logical date, failing which the draft is rejected with `ERR_VACATE_DATE_TOO_SOON`. Only one active agreement may exist per case: creating a draft while another agreement of the same case is `OFFERED`, `COUNTERED`, or `ACCEPTED` is rejected with `ERR_ACTIVE_AGREEMENT_EXISTS`; an existing `DRAFT`, by contrast, is simply superseded — flipped to `SUPERSEDED` — as the new draft is created (the flip happens during creation processing, so a creation that then fails the property lookup below still leaves the prior draft `SUPERSEDED`). Creation computes `provisional_assistance_cents` on the `SELF_REPORTED` condition basis — reading the earliest-registered property of the case's loan for the occupancy multiplier, and failing with `ERR_PROPERTY_NOT_FOUND` when no property is registered for that loan — stamps `created_by_specialist_id` from the specialist's `X-User-ID`, starts `round_number` at 0, leaves `final_assistance_cents` null, and increments the case's `version`.

The provisional assistance quote is assembled in a pinned evaluation order: tier selection, then the occupancy multiplier, then rounding, then the hardship bonus, then the floor, then the cap. The tier base is selected by the loan's unpaid principal balance: under 10,000,000 cents ($100,000) the base is 300,000 cents; from 10,000,000 cents up to but not including 25,000,000 cents ($250,000) the base is 500,000 cents — each tier boundary is inclusive of its lower bound; from 25,000,000 cents up to but not including 50,000,000 cents ($500,000) the base is 750,000 cents; and at 50,000,000 cents or more the base is 1,150,000 cents. The tier base is then multiplied by an occupancy multiplier drawn from the property's `occupancy_type` — 1.0 for `OWNER_OCCUPIED`, 0.8 for `TENANT_OCCUPIED`, 0.5 for `SECOND_HOME` — and that product is rounded half-up to whole cents, the only rounding step in the quote. A hardship bonus is added next, drawn from the borrower's `hardship_type`: 100,000 cents for `INVOLUNTARY_UNEMPLOYMENT`, 50,000 for `MEDICAL`, 25,000 for `DIVORCE`, and nothing for `NONE`. The result is then raised to a floor of 150,000 cents when it falls short, and only after that floor is applied is it capped at 1,200,000 cents — the floor is always applied before the cap.

Offering the draft to the borrower moves the agreement from `DRAFT` to `OFFERED` (from any other state the offer is refused with `ERR_AGREEMENT_INVALID_STATE`) and sets `offer_expires_at` to the current logical timestamp plus the supplied `offer_valid_days` days (a required integer input), leaving `round_number` at 0. The borrower answers with a counter or an acceptance, and both borrower actions enforce the ownership rule of §2.1 — an `X-User-ID` that does not equal the case's `borrower_id` draws `ERR_FORBIDDEN`. A counter is valid only from `OFFERED` and only while the offer has not lapsed, and its guards run in the same pinned order as acceptance below — state first, then ownership, then expiry: if the current logical time has passed `offer_expires_at`, the counter is rejected with `ERR_OFFER_EXPIRED`. The counter's `proposed_vacate_date` replaces the agreement's `vacate_date` and must itself satisfy the ten-day notice (`ERR_VACATE_DATE_TOO_SOON`); the provisional amount is left unchanged, and the agreement moves to `COUNTERED`.

A specialist answers a counter by re-offering: the agreement must be `COUNTERED`, and the negotiation-round cap applies — re-offering when `round_number` has already reached 3 is rejected with `ERR_NEGOTIATION_ROUND_LIMIT`. The re-offer replaces `vacate_date` with the new input (the ten-day notice applies again), increments `round_number` by one, recomputes `provisional_assistance_cents` from scratch, resets `offer_expires_at` to now plus the new `offer_valid_days` (again a required integer input), and returns the agreement to `OFFERED`.

Acceptance moves the agreement from `OFFERED` to `ACCEPTED`. Its guards run in a pinned order: the agreement must be `OFFERED` (`ERR_AGREEMENT_INVALID_STATE`), ownership must hold (`ERR_FORBIDDEN`), and the offer must not have lapsed (`ERR_OFFER_EXPIRED`) — this temporal check is evaluated before any lien-clearance check. Then, for `DEED_IN_LIEU` cases only, every junior lien on the case's most recently created title commitment must be out of `UNRELEASED`; an outstanding lien blocks acceptance with `ERR_JUNIOR_LIENS_OUTSTANDING`, a check skipped entirely for `CASH_FOR_KEYS`. Acceptance stamps `accepted_at` with the current logical timestamp and bubbles up: the case moves from `TERMS_NEGOTIATION` to `AGREEMENT_ACTIVE` with a version increment, and for deed-in-lieu cases the system creates a DeficiencyWaiver in `DRAFT` status — its `case_id` set from the case, its `loan_id` copied from the case, its `projected_waiver_cents` computed per the projected variant described in §3.8, and its `waived_amount_cents` and `pre_waiver_deficiency_cents` initialized to zero.

Offer expiry itself is lazy. An `OFFERED` agreement flips to `EXPIRED` when it is read or acted upon after `offer_expires_at` has passed: on an accept or counter the expiry guard reports `ERR_OFFER_EXPIRED` and the agreement then flips to `EXPIRED`, while plain reads flip it silently. The clock-setting capability performs no sweep of its own.

A `WorkoutManager` may terminate an `ACCEPTED` agreement — termination from any other state is refused with `ERR_AGREEMENT_INVALID_STATE` — moving it to `TERMINATED`; when the case is in `AGREEMENT_ACTIVE` at that moment, the case reverts from `AGREEMENT_ACTIVE` to `TERMS_NEGOTIATION` so that terms can be renegotiated. Termination also arrives by cascade, on case withdrawal and on eviction filing. Once an agreement exists, the case's `remaining_assistance_cents` is the applicable agreement's assistance minus the case's `total_disbursed_cents`; the applicable agreement is the case's most recently created `ACCEPTED` or `COMPLETED` agreement when one exists, otherwise the case's most recently created agreement, and its assistance is `final_assistance_cents` when the agreement is `ACCEPTED` or `COMPLETED` with `final_assistance_cents` set, otherwise `provisional_assistance_cents`; until an agreement exists, `remaining_assistance_cents` is null. An agreement in `COMPLETED`, `EXPIRED`, `TERMINATED`, or `SUPERSEDED` is terminal and rejects every further action.

### 3.6. Handover Inspection and Condition Assessment

Inspections are scheduled by the specialist against a case. The payload identifies the `case_id`, the `inspector_id` (the opaque identifier the acting inspector will later authenticate with), the `appointment_type` — `HANDOVER` or `RE_INSPECTION` — and a half-open interval from `scheduled_start` to `scheduled_end`, where the end must be strictly later than the start (a non-later end is rejected with `ERR_INVALID_REQUEST`). Case posture gates the type: a `HANDOVER` appointment requires the case to be in `AGREEMENT_ACTIVE` or `VACATE_PENDING`, while a `RE_INSPECTION` requires `VACATE_PENDING`; scheduling against any other case state is refused with `ERR_CASE_INVALID_STATE`. Two constraints are then evaluated in a pinned order, calendar conflict first, notice second. For the calendar, the new appointment's half-open interval — extended by a 30-minute travel buffer at its end — must not intersect any other `SCHEDULED` appointment's similarly buffered interval for the same `inspector_id`; intervals that merely touch are allowed, and a genuine conflict is rejected with `ERR_INSPECTOR_SCHEDULE_CONFLICT`. For the notice, `scheduled_start` must fall at least 24 hours after the current logical time, failing which the request is rejected with `ERR_INSPECTION_TOO_SOON`. Scheduling a `HANDOVER` appointment while the case is in `AGREEMENT_ACTIVE` also advances the case automatically from `AGREEMENT_ACTIVE` to `VACATE_PENDING`.

An appointment is born `SCHEDULED` and ends in one of three terminal states: `COMPLETED`, `CANCELLED`, or `NO_ACCESS`. The specialist may cancel a `SCHEDULED` appointment; the inspector assigned to it may record a no-access outcome — both demand the `SCHEDULED` state, otherwise `ERR_APPOINTMENT_INVALID_STATE`, and the no-access action additionally requires the acting inspector's `X-User-ID` to equal the appointment's `inspector_id` (`ERR_FORBIDDEN`). A no-access outcome is holdover evidence rather than a case transition: the case state does not change, and the specialist may cancel while the manager weighs escalation.

The inspector creates a draft inspection report on a `SCHEDULED` appointment — again with the identity match against `inspector_id`, and again `ERR_APPOINTMENT_INVALID_STATE` when the appointment is anything but `SCHEDULED`. The draft carries `broom_clean_verified` (a required boolean: the inspector's verification of the `BROOM_CLEAN` condition standard), a `keys_returned_count` of zero or more (a required integer), and a `line_items` array — which may be omitted, defaulting to empty — in which each line pairs an `item_code` — one of `CLEANLINESS_FAIL`, `DEBRIS_REMOVAL`, `APPLIANCE_REMOVED`, `FIXTURE_DAMAGE`, or `STRUCTURAL_DAMAGE` — with a `severity` of `STANDARD` or `MATERIAL`; a line missing either key, or carrying a value outside its declared domain, is rejected with `ERR_INVALID_ENUM`. The report is born `DRAFT`, with its `appointment_id` taken from the creation path and its `case_id` copied from the appointment.

Submitting the report is the pivot of the whole handover. The report must be `DRAFT` — a second submit is refused with `ERR_REPORT_INVALID_STATE` — and the acting inspector's identity must match the appointment's `inspector_id`. On submit, the system prices the condition findings: each line item's base amount — 14,999 cents for `CLEANLINESS_FAIL`, 24,999 for `DEBRIS_REMOVAL`, 39,999 for `APPLIANCE_REMOVED`, 59,999 for `FIXTURE_DAMAGE`, and 149,999 for `STRUCTURAL_DAMAGE` — is multiplied by the severity multiplier, 1.0 for `STANDARD` and 1.5 for `MATERIAL`, and each product is rounded half-up to whole cents before any summation; `total_deduction_cents` is then the sum of those rounded line amounts. The per-item rounding order is pinned, because it genuinely differs from the alternative: two `MATERIAL` lines on `CLEANLINESS_FAIL` and `DEBRIS_REMOVAL` round to 22,499 and 37,499 cents respectively for a total of 59,998, whereas summing the raw products first would yield 59,997 — the per-item order is the only correct one. The report's `result` is then derived: `FAILED` when `broom_clean_verified` is false or any `STRUCTURAL_DAMAGE` line is present; otherwise `PASSED_WITH_DEDUCTIONS` when `total_deduction_cents` is greater than zero; otherwise `PASSED`.

The submission cascades in hops. First, the appointment moves from `SCHEDULED` to `COMPLETED`, and the case moves from `VACATE_PENDING` to `HANDOVER_INSPECTION`, stamping `handover_date` with the logical date at submit and setting `keys_returned` — true exactly when the latest submitted handover report's `keys_returned_count` is greater than zero. Each of these two movements is conditional on its source state still holding at submit time, and the result fork below rides the case movement: a stale draft submitted after its appointment was cancelled or after the case left `VACATE_PENDING` still prices and records its result but moves nothing. Second, the case forks on the result: a `PASSED` or `PASSED_WITH_DEDUCTIONS` report advances it from `HANDOVER_INSPECTION` to `DISBURSEMENT_PENDING`, flips the agreement's `condition_basis` from `SELF_REPORTED` to `INSPECTED`, and computes `final_assistance_cents` (which in turn recomputes the case's `remaining_assistance_cents`); a `FAILED` report loops the case back from `HANDOVER_INSPECTION` to `VACATE_PENDING` for cure and re-inspection. The case's `version` increments.

The final assistance settlement starts from the accepted agreement's `provisional_assistance_cents` and subtracts two independently computed components: the report's `total_deduction_cents` and the capped holdover penalty. The holdover penalty accrues at 15,000 cents for each whole day the handover was late beyond a three-day grace period: take the whole-day difference between the case's `handover_date` and the agreement's `vacate_date`, subtract the three grace days, floor at zero, and multiply by 15,000 — so a handover exactly on the third day after the vacate date (the last grace day) accrues nothing, while the fourth day accrues 15,000 cents. The accrued penalty is then capped at half of the provisional assistance, that half computed by multiplying `provisional_assistance_cents` by 0.5 and rounding half-up to whole cents; the applied penalty is the lesser of the accrual and the cap. The `final_assistance_cents` is the provisional amount minus the deductions minus the capped penalty, floored at zero. A zero final assistance still advances the case to `DISBURSEMENT_PENDING` — though, as §3.7 makes clear, no disbursement can be created for a zero remaining amount.

### 3.7. Relocation Assistance Disbursement

Once the case reaches `DISBURSEMENT_PENDING`, the specialist requests a disbursement against it — from any other case state the request is refused with `ERR_CASE_INVALID_STATE`. The payload carries the `agreement_id` of the funding agreement — which must resolve (§2.9) but is not cross-checked against the addressed case — the `amount_cents` requested, and an optional `purpose` that currently supports only `RELOCATION_ASSISTANCE`, its default. The amount must be strictly greater than zero (`ERR_DISBURSEMENT_NOT_POSITIVE`) and must not exceed the case's `remaining_assistance_cents` (`ERR_DISBURSEMENT_EXCEEDS_REMAINING`), the ceiling evaluated last, after the state and positivity checks. The disbursement is born `PENDING` with the specialist's `X-User-ID` recorded as `requested_by_user_id`.

Approval and release belong to the `DisbursementOfficer` under the segregation-of-duties rules of §2.11. Approving moves a `PENDING` disbursement to `APPROVED` and records `approved_by_user_id`; approving from any other state draws `ERR_DISBURSEMENT_INVALID_STATE`, and an approver who is the requester draws `ERR_SOD_APPROVER_EQUALS_REQUESTER`. Releasing moves an `APPROVED` disbursement to `RELEASED`, records `released_by_user_id` and the `released_at` logical timestamp, requires a releaser distinct from the approver (`ERR_SOD_RELEASER_EQUALS_APPROVER`), and — keyed to the physical handover — requires the case's `keys_returned` to be true (`ERR_KEYS_NOT_RETURNED`). A release adds the disbursement's `amount_cents` to the case's `total_disbursed_cents` — the running sum of `amount_cents` over the case's `RELEASED` disbursements — and recomputes `remaining_assistance_cents`.

The zero-remaining fork closes the program loop. When a release brings `remaining_assistance_cents` to zero and keys have been returned, a deed-in-lieu case advances automatically from `DISBURSEMENT_PENDING` to `RECORDING_PENDING`, while a cash-for-keys case completes outright: the case moves to `COMPLETED`, its agreement moves from `ACCEPTED` to `COMPLETED`, the loan moves from `WORKOUT_IN_PROGRESS` to `DEED_IN_LIEU_COMPLETED` with `servicing_system_synced` set to true, and the versions of case and loan increment.

Two corrective actions round out the lifecycle. A specialist may void a disbursement in `PENDING` or `APPROVED` — from any other state the void draws `ERR_DISBURSEMENT_INVALID_STATE` — moving it to `VOIDED`; voiding also arrives by cascade, on case withdrawal and on eviction filing. A `WorkoutManager` may claw back a `RELEASED` disbursement, moving it to `CLAWED_BACK` and subtracting its `amount_cents` from the case's `total_disbursed_cents`, with `remaining_assistance_cents` recomputed — the compensating action of release under the assistance-conservation invariant (INV-ASSISTANCE). `RELEASED`, `VOIDED`, and `CLAWED_BACK` are terminal.

### 3.8. Deficiency Waiver, Deed Recording, and Case Completion

Deed-in-lieu cases carry a deficiency waiver, created in `DRAFT` status at the moment the agreement is accepted (§3.5). A renegotiation cycle that reaches acceptance again creates another waiver; wherever the system consults the case's waiver — the confirmation gate, execution — it uses the earliest-created one. The waiver's amounts rest on a common accrual base: the loan's `unpaid_principal_balance_cents`, `accrued_interest_cents`, `escrow_advances_cents`, and `foreclosure_fees_cents`, summed. The projected variant — stored as `projected_waiver_cents` at creation — is forward-looking: count the whole days from the agreement's acceptance date to the agreed `vacate_date`, multiply that count by the loan's `per_diem_interest_cents`, add the accrual base, subtract the loan's `fair_market_value_cents`, and floor the result at zero. The final variant — stored as `final_waiver_cents` at execution — repeats the computation with the actual recordation date (the calendar date of the recording's `recorded_at`) in place of the vacate date. The two variants legitimately diverge whenever recordation lands on a different date than the agreed vacate date.

`LegalCounsel` attaches the executed-waiver documentation, moving the waiver from `DRAFT` to `DOCUMENTED` and recording the supplied `document_reference`; documenting from any other state is refused with `ERR_WAIVER_INVALID_STATE`. Execution itself is not a client action: it arrives with the deed-recording confirmation described below, at which point `final_waiver_cents` is computed per the final variant, `pre_waiver_deficiency_cents` snapshots that final amount as the invariant base taken before zeroing, `waived_amount_cents` is set to `final_waiver_cents`, and the loan's `deficiency_balance_cents` drops to zero under the debt-conservation invariant (INV-DEBT). Should the waiver later prove defective, a `WorkoutManager` may rescind an `EXECUTED` waiver — from any other state, `ERR_WAIVER_INVALID_STATE` — moving it to `RESCINDED`, resetting `waived_amount_cents` to zero, and restoring the loan's `deficiency_balance_cents` to `pre_waiver_deficiency_cents`, the compensating action of execution under INV-DEBT.

The deed recording package is created by `LegalCounsel` against a case in `RECORDING_PENDING` — deed-in-lieu only, and creating one against a `CASH_FOR_KEYS` case is rejected with `ERR_INVALID_REQUEST` — with the recording `county` supplied in the payload; the package is born `PENDING`, and creation is not blocked by an existing package on the case. Counsel then submits it to the county (`PENDING` to `SUBMITTED`; any other source state draws `ERR_RECORDING_INVALID_STATE`) and later records one of two county outcomes. A rejection moves the package from `SUBMITTED` to `REJECTED` and preserves the supplied `rejection_reason`; the case itself remains in `RECORDING_PENDING`, and a fresh recording package may be created. A confirmation moves the package from `SUBMITTED` to `RECORDED`, stamps the county's `instrument_number` and the `recorded_at` logical timestamp, and is gated on two further preconditions beyond state: the case's deficiency waiver must be `DOCUMENTED` (`ERR_WAIVER_NOT_DOCUMENTED`), and the logical date at confirm must be no later than thirty days after the case's `handover_date` (`ERR_RECORDING_DEADLINE_PASSED`).

Confirmation fires the completion cascade in hops. Hop one moves the case from `RECORDING_PENDING` to `COMPLETED`. Hop two rides case completion: the agreement moves from `ACCEPTED` to `COMPLETED`, the waiver executes as described above with its final amounts, and the loan moves from `WORKOUT_IN_PROGRESS` to `DEED_IN_LIEU_COMPLETED` with `servicing_system_synced` set to true. Hop three rides the waiver execution: the loan's `deficiency_balance_cents` becomes the snapshot minus the waived amount — zero, since the two are equal — and a loan whose `foreclosure_referral_status` was `REFERRED` has it withdrawn to `WITHDRAWN`. The versions of the case, the waiver, and the loan each increment.

### 3.9. Holdover Escalation and the Eviction Docket

When an occupant stays past the agreed date, a `WorkoutManager` escalates. Escalation is available while the case is in `AGREEMENT_ACTIVE`, `VACATE_PENDING`, `HANDOVER_INSPECTION`, or `DISBURSEMENT_PENDING` — and it requires an accepted agreement to measure the grace window against, its absence rejected with `ERR_AGREEMENT_NOT_FOUND` — and only once the current logical date has passed the third day after the accepted agreement's `vacate_date` — the grace window is the vacate date itself plus the three days following it, and escalating before that window has fully elapsed is rejected with `ERR_HOLDOVER_GRACE_NOT_ELAPSED`. Escalation creates an EvictionCase for the case — born `ESCALATED`, its `reason` fixed at `HOLDOVER` — moves the case to `HOLDOVER_ESCALATED`, increments the case's `version`, and answers 201 with the new eviction case.

From there the eviction docket belongs to `LegalCounsel`. Filing the eviction in court moves the eviction case from `ESCALATED` to `FILED`, recording the supplied `court_reference` and the `filed_at` logical timestamp. Filing is the point of no return for the workout: the case moves from `HOLDOVER_ESCALATED` to `EVICTION_IN_PROGRESS`, the accepted agreement is terminated (`ACCEPTED` to `TERMINATED`), every disbursement of the case still `PENDING` or `APPROVED` is voided, and for deed-in-lieu cases the loan moves from `WORKOUT_IN_PROGRESS` to `FORECLOSURE_PROCEEDING`. Recording the writ moves the docket from `FILED` to `WRIT_ISSUED`, and recording the execution moves it from `WRIT_ISSUED` to `EVICTED`, closing the case as `CLOSED_EVICTED`. Each of these transitions demands its exact source state — filing a non-`ESCALATED` docket, recording a writ on a non-`FILED` one, recording an execution on a non-`WRIT_ISSUED` one, or dismissing from anywhere but `ESCALATED` or `FILED` — is refused with `ERR_EVICTION_INVALID_STATE`.

Dismissal is the docket's safety valve, and its effect on the workout depends on both the source state and the supplied `dismissal_reason`. Dismissing an `ESCALATED` docket with `OCCUPANT_VACATED` returns the case from `HOLDOVER_ESCALATED` to `VACATE_PENDING` so the handover can proceed; dismissing it with `OTHER` leaves the case in `HOLDOVER_ESCALATED`. Dismissing a `FILED` docket with `OCCUPANT_VACATED` opens the renegotiation cycle: the case moves from `EVICTION_IN_PROGRESS` back to `TERMS_NEGOTIATION`, the prior agreement stays `TERMINATED`, and for deed-in-lieu cases the loan returns from `FORECLOSURE_PROCEEDING` to `WORKOUT_IN_PROGRESS`. Dismissing a `FILED` docket with `OTHER` leaves the case in `EVICTION_IN_PROGRESS`. `EVICTED` and `DISMISSED` are terminal for the docket.

## 4. Endpoint Definitions

Operations that create a new resource — boarding a loan, registering a borrower or property, opening a case, creating a listing, ordering a title commitment, adding a junior lien, drafting an agreement, scheduling an appointment, creating a draft report, requesting a disbursement, creating a deed-recording package — return `201 Created`. So does holdover escalation, which materializes a new EvictionCase. Operations that modify an existing resource, and all reads, return `200 OK`. Request payloads, response shapes, and side effects for every endpoint are specified in the workflow narratives of §3; the table below is a locator, not a contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | ServicingAdmin |
| POST | `/property-solutions/loans` | Board a loan | ServicingAdmin |
| GET | `/property-solutions/loans/{id}` | Get a loan | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer |
| GET | `/property-solutions/loans` | List loans | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer |
| POST | `/property-solutions/borrowers` | Register a borrower | ServicingAdmin |
| GET | `/property-solutions/borrowers/{id}` | Get a borrower; Borrower role reads only its own id | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, Borrower |
| POST | `/property-solutions/properties` | Register the subject property for a loan | ServicingAdmin |
| GET | `/property-solutions/properties/{id}` | Get a property | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer, Inspector |
| GET | `/property-solutions/properties` | List properties, filterable by loan | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer, Inspector |
| POST | `/property-solutions/cases` | Open a workout case | PropertySolutionsSpecialist |
| GET | `/property-solutions/cases/{id}` | Get a case; Borrower role reads only its own cases | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer, Inspector, Borrower |
| GET | `/property-solutions/cases` | List cases | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer, Inspector |
| POST | `/property-solutions/cases/{id}/submit` | Submit for eligibility review | PropertySolutionsSpecialist |
| POST | `/property-solutions/cases/{id}/evaluate-eligibility` | Record the eligibility decision | PropertySolutionsSpecialist |
| POST | `/property-solutions/cases/{id}/marketing-exception` | Grant a marketing-period exception | WorkoutManager |
| POST | `/property-solutions/cases/{id}/certify-marketing` | Certify the marketing period is satisfied | PropertySolutionsSpecialist |
| POST | `/property-solutions/cases/{id}/certify-title` | Certify title is clear | PropertySolutionsSpecialist |
| POST | `/property-solutions/cases/{id}/escalate-holdover` | Escalate an occupant holdover after the grace period | WorkoutManager |
| POST | `/property-solutions/cases/{id}/withdraw` | Withdraw the case | PropertySolutionsSpecialist, Borrower |
| GET | `/property-solutions/cases/{id}/listings` | Listings for a case | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer, Inspector, Borrower |
| GET | `/property-solutions/cases/{id}/title-commitments` | Title commitments for a case | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer, Inspector, Borrower |
| GET | `/property-solutions/cases/{id}/agreements` | Agreements for a case | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer, Inspector, Borrower |
| GET | `/property-solutions/cases/{id}/inspection-appointments` | Appointments for a case | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer, Inspector, Borrower |
| GET | `/property-solutions/cases/{id}/inspection-reports` | Reports for a case | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer, Inspector, Borrower |
| GET | `/property-solutions/cases/{id}/disbursements` | Disbursements for a case | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer, Borrower |
| GET | `/property-solutions/cases/{id}/deficiency-waivers` | Deficiency waivers for a case | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer, Borrower |
| GET | `/property-solutions/cases/{id}/deed-recordings` | Deed recordings for a case | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer, Borrower |
| GET | `/property-solutions/cases/{id}/eviction-cases` | Eviction cases for a case | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer, Borrower |
| POST | `/property-solutions/listings` | List the property for the marketing period | PropertySolutionsSpecialist |
| GET | `/property-solutions/listings/{id}` | Get a listing; recomputes creditable days for non-closed listings | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer, Inspector, Borrower |
| POST | `/property-solutions/listings/{id}/suspend` | Suspend marketing, opening a suspension interval | PropertySolutionsSpecialist |
| POST | `/property-solutions/listings/{id}/resume` | Resume marketing, closing the open suspension | PropertySolutionsSpecialist |
| POST | `/property-solutions/listings/{id}/close` | Close the listing, freezing creditable days | PropertySolutionsSpecialist |
| GET | `/property-solutions/listings/{id}/suspensions` | Suspension intervals for a listing | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer, Inspector, Borrower |
| POST | `/property-solutions/title-commitments` | Order a title commitment | TitleOfficer |
| GET | `/property-solutions/title-commitments/{id}` | Get a title commitment | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer |
| POST | `/property-solutions/title-commitments/{id}/receive` | Record receipt of the commitment | TitleOfficer |
| POST | `/property-solutions/title-commitments/{id}/liens` | Add a junior lien to a commitment | TitleOfficer |
| GET | `/property-solutions/title-commitments/{id}/liens` | Liens on a commitment | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer |
| POST | `/property-solutions/title-commitments/{id}/lien-releases` | Release a junior lien | TitleOfficer |
| POST | `/property-solutions/cases/{id}/agreements` | Draft a settlement agreement | PropertySolutionsSpecialist |
| GET | `/property-solutions/agreements/{id}` | Get an agreement | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer, Borrower |
| POST | `/property-solutions/agreements/{id}/offer` | Offer the draft to the borrower | PropertySolutionsSpecialist |
| POST | `/property-solutions/agreements/{id}/counter` | Borrower counters with a different vacate date | Borrower |
| POST | `/property-solutions/agreements/{id}/reoffer` | Re-offer after a counter | PropertySolutionsSpecialist |
| POST | `/property-solutions/agreements/{id}/accept` | Borrower accepts the offer | Borrower |
| POST | `/property-solutions/agreements/{id}/terminate` | Terminate an accepted agreement | WorkoutManager |
| GET | `/property-solutions/agreements/{id}/disbursements` | Disbursements against an agreement | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer, Borrower |
| POST | `/property-solutions/inspection-appointments` | Schedule an inspection | PropertySolutionsSpecialist |
| GET | `/property-solutions/inspection-appointments/{id}` | Get an appointment | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer, Inspector |
| POST | `/property-solutions/inspection-appointments/{id}/cancel` | Cancel a scheduled appointment | PropertySolutionsSpecialist |
| POST | `/property-solutions/inspection-appointments/{id}/no-access` | Record no access at the appointment | Inspector |
| POST | `/property-solutions/inspection-appointments/{id}/reports` | Create a draft inspection report | Inspector |
| GET | `/property-solutions/inspection-appointments/{id}/reports` | Reports for an appointment | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer, Inspector |
| GET | `/property-solutions/inspection-reports/{id}` | Get a report | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer, Inspector, Borrower |
| POST | `/property-solutions/inspection-reports/{id}/submit` | Submit the report, driving the handover cascade | Inspector |
| POST | `/property-solutions/cases/{id}/disbursements` | Request a relocation-assistance disbursement | PropertySolutionsSpecialist |
| GET | `/property-solutions/disbursements/{id}` | Get a disbursement | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer |
| POST | `/property-solutions/disbursements/{id}/approve` | Approve a disbursement | DisbursementOfficer |
| POST | `/property-solutions/disbursements/{id}/release` | Release funds at key delivery | DisbursementOfficer |
| POST | `/property-solutions/disbursements/{id}/void` | Void a pending or approved disbursement | PropertySolutionsSpecialist |
| POST | `/property-solutions/disbursements/{id}/clawback` | Claw back a released disbursement | WorkoutManager |
| GET | `/property-solutions/deficiency-waivers/{id}` | Get a deficiency waiver | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer, Borrower |
| POST | `/property-solutions/deficiency-waivers/{id}/document` | Attach executed waiver documentation | LegalCounsel |
| POST | `/property-solutions/deficiency-waivers/{id}/rescind` | Rescind an executed waiver | WorkoutManager |
| GET | `/property-solutions/loans/{id}/deficiency-waivers` | Waivers for a loan | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer |
| POST | `/property-solutions/cases/{id}/deed-recordings` | Create a deed-recording package | LegalCounsel |
| GET | `/property-solutions/deed-recordings/{id}` | Get a deed recording | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer |
| POST | `/property-solutions/deed-recordings/{id}/submit` | Submit the package to the county | LegalCounsel |
| POST | `/property-solutions/deed-recordings/{id}/confirm` | Confirm recordation, driving the completion cascade | LegalCounsel |
| POST | `/property-solutions/deed-recordings/{id}/reject` | Record the county's rejection | LegalCounsel |
| GET | `/property-solutions/eviction-cases/{id}` | Get an eviction case | ServicingAdmin, PropertySolutionsSpecialist, WorkoutManager, TitleOfficer, LegalCounsel, DisbursementOfficer |
| POST | `/property-solutions/eviction-cases/{id}/file` | File the eviction in court | LegalCounsel |
| POST | `/property-solutions/eviction-cases/{id}/writ` | Record writ issuance | LegalCounsel |
| POST | `/property-solutions/eviction-cases/{id}/evicted` | Record eviction execution | LegalCounsel |
| POST | `/property-solutions/eviction-cases/{id}/dismiss` | Dismiss the eviction | LegalCounsel |

## 5. Error Code Catalogue

Trigger conditions for every error are specified in the narratives of §2 and §3; this catalogue is a locator for identifiers and status codes only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ENUM` | 400 Bad Request |
| `ERR_LOAN_NOT_FOUND` | 404 Not Found |
| `ERR_BORROWER_NOT_FOUND` | 404 Not Found |
| `ERR_PROPERTY_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_LISTING_NOT_FOUND` | 404 Not Found |
| `ERR_TITLE_COMMITMENT_NOT_FOUND` | 404 Not Found |
| `ERR_LIEN_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_DISBURSEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_WAIVER_NOT_FOUND` | 404 Not Found |
| `ERR_RECORDING_NOT_FOUND` | 404 Not Found |
| `ERR_EVICTION_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_LOAN_INVALID_STATE` | 409 Conflict |
| `ERR_CASE_INVALID_STATE` | 409 Conflict |
| `ERR_LISTING_INVALID_STATE` | 409 Conflict |
| `ERR_TITLE_INVALID_STATE` | 409 Conflict |
| `ERR_LIEN_INVALID_STATE` | 409 Conflict |
| `ERR_AGREEMENT_INVALID_STATE` | 409 Conflict |
| `ERR_APPOINTMENT_INVALID_STATE` | 409 Conflict |
| `ERR_REPORT_INVALID_STATE` | 409 Conflict |
| `ERR_DISBURSEMENT_INVALID_STATE` | 409 Conflict |
| `ERR_RECORDING_INVALID_STATE` | 409 Conflict |
| `ERR_EVICTION_INVALID_STATE` | 409 Conflict |
| `ERR_WAIVER_INVALID_STATE` | 409 Conflict |
| `ERR_ACTIVE_LISTING_EXISTS` | 409 Conflict |
| `ERR_ACTIVE_AGREEMENT_EXISTS` | 409 Conflict |
| `ERR_LIEN_POSITION_DUPLICATE` | 409 Conflict |
| `ERR_INSPECTOR_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_TITLE_VERSION` | 412 Precondition Failed |
| `ERR_ELIGIBILITY_CRITERIA_NOT_MET` | 422 Unprocessable Entity |
| `ERR_OFFER_EXPIRED` | 422 Unprocessable Entity |
| `ERR_VACATE_DATE_TOO_SOON` | 422 Unprocessable Entity |
| `ERR_INSPECTION_TOO_SOON` | 422 Unprocessable Entity |
| `ERR_MARKETING_PERIOD_NOT_MET` | 422 Unprocessable Entity |
| `ERR_HOLDOVER_GRACE_NOT_ELAPSED` | 422 Unprocessable Entity |
| `ERR_RECORDING_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_LISTING_MISSING` | 422 Unprocessable Entity |
| `ERR_TITLE_COMMITMENT_MISSING` | 422 Unprocessable Entity |
| `ERR_JUNIOR_LIENS_OUTSTANDING` | 422 Unprocessable Entity |
| `ERR_KEYS_NOT_RETURNED` | 422 Unprocessable Entity |
| `ERR_WAIVER_NOT_DOCUMENTED` | 422 Unprocessable Entity |
| `ERR_SOD_APPROVER_EQUALS_REQUESTER` | 422 Unprocessable Entity |
| `ERR_SOD_RELEASER_EQUALS_APPROVER` | 422 Unprocessable Entity |
| `ERR_DISBURSEMENT_NOT_POSITIVE` | 422 Unprocessable Entity |
| `ERR_DISBURSEMENT_EXCEEDS_REMAINING` | 422 Unprocessable Entity |
| `ERR_SETTLEMENT_EXCEEDS_LIEN` | 422 Unprocessable Entity |
| `ERR_NEGOTIATION_ROUND_LIMIT` | 422 Unprocessable Entity |
