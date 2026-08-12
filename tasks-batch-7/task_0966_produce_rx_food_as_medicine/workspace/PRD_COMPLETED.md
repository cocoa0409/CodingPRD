# Produce Rx & Food as Medicine API — Product Requirements Document

## 1. Introduction

Food-as-medicine programs sit at an uncomfortable intersection: a clinic diagnoses a diet-related condition and writes what is effectively a prescription for fresh produce; a funder underwrites the benefit; a grocery store, farmers market, or mobile market must redeem that benefit at the register; and everyone — clinician, funder, program operator — needs to know whether any of it actually improved patient health. This document specifies the API that runs such a program end to end. It covers clinic referral and enrollment, monthly benefit allocation through benefit cycles and vouchers, retailer redemption with a Double-Up produce incentive, nutrition education and engagement tracking, A1c and other biometric outcome measurement, funder reporting, and renewal of lapsed participation.

The platform serves six distinct constituencies with sharply segregated duties: program operators configure and run the program but may never adjudicate a funder's own report; funder representatives commit and release money but never enroll patients; clinic staff manage their own patients and referrals; retail cashiers settle redemptions at their own tills; educators run nutrition sessions; and enrolled participants retain read-only visibility into their own records. Because money, health data, and multi-party adjudication all flow through the same API, the specification leans heavily on explicit state machines, an auditable reserve ledger, deterministic rounding, optimistic concurrency on the two aggregate roots where supersession occurs, and a logical clock so that time-dependent rules (referral expiry, enrollment lapse, daily match caps) are reproducible rather than wall-clock accidents.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming one of the six declared roles. A request missing either header, or presenting a role string that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the target endpoint, or whose entity-backed ownership check fails, is rejected with `ERR_FORBIDDEN` (HTTP 403).

The six roles, spelled exactly as the API expects them, are `ProgramAdmin`, `FunderAnalyst`, `ClinicStaff`, `Participant`, `RetailerStaff`, and `Educator`. Their identities bind to `X-User-ID` as follows.

- When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but never compares it to any entity's `id`.
- When `X-User-Role` is `FunderAnalyst`, `X-User-ID` is the `id` of the acting Funder; ownership checks on any resource that references a Funder — a funding pool's `funder_id`, or the `funder_id` of the pool a report covers — compare that foreign-key field to `X-User-ID`. The comparison gates only the mutating acts — funding a pool, accepting or returning a report; reads of funders, pools, reports, programs, and program summaries are not ownership-scoped, and any `FunderAnalyst` may read any of them.
- When `X-User-Role` is `ClinicStaff`, `X-User-ID` is the `id` of the acting Clinic; ownership checks on patients, referrals, and renewals compare the resource's `clinic_id` (or the `clinic_id` of the enrollment's patient) to `X-User-ID`. These comparisons gate the mutating acts — patient registration and consent changes, referral submission, appeal, and withdrawal, biometric recording, and renewal creation, submission, and resubmission; read endpoints and listings are not ownership-scoped for `ClinicStaff`.
- When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting Patient; a participant reads only their own records — their own patient profile, their own enrollments, and their own vouchers — and any attempt to reach another patient's record is `ERR_FORBIDDEN`.
- When `X-User-Role` is `RetailerStaff`, `X-User-ID` is the `id` of the acting Retailer; a redemption's `retailer_id` must equal `X-User-ID`, and a retail cashier sees only their own retailer's redemptions. Reads of retailer records themselves are not ownership-scoped; only redemption creation, redemption reads, and redemption voids are scoped to the acting retailer.
- When `X-User-Role` is `Educator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; it is recorded as `educator_ref` on each education session the educator schedules, purely for audit.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits. It is taken from the server's wall clock, not the logical clock of §2.5.
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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100, and `offset` defaults to 0; out-of-range values are clamped to those bounds rather than rejected, while a non-integer `limit` or `offset` is `ERR_VALIDATION`. Results are always sorted by `created_at` ascending, with ties broken by creation order. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`, so a client can page deterministically through any collection.

### 2.4. Resource Identity and Common Fields

Every persisted resource exposes an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC format with three fractional digits. Most resources additionally carry `updated_at`, refreshed on every mutation, and `version`, an integer that increments by one on every mutation of that resource; at creation `updated_at` equals `created_at` and `version` is 1.

Two record types are deliberately thinner. An education completion and a biometric reading are append-only, immutable observations; each carries only `id` and `created_at` alongside its domain fields, and both `updated_at` and `version` are absent from these two resources.

### 2.5. The Logical Clock

All time-dependent behavior in this API — daily Double-Up caps, referral expiry, enrollment lapse, report windows — reads a server-held logical clock, never the wall clock. Before any client call, the logical clock reads exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock time on its own. A `ProgramAdmin` may advance it through an admin-only test-driving capability that accepts a `to_iso8601` instant and answers with the resulting `current_utc`; no entity is mutated by doing so. Timestamps the server assigns during business operations — every resource's `created_at` and `updated_at`, a redemption's `redeemed_at`, an enrollment's `lapsed_at` — are taken from this logical clock, and all calendar-date comparisons are made in UTC; an ISO 8601 instant supplied without a UTC offset is read as UTC.

### 2.6. Money, Cents, and Rounding

Every monetary quantity in the system is an integer number of cents: benefit face values, pool ledger amounts, redemption line amounts, match amounts, and report totals are all computed and stored as whole cents. Where a multiplication produces a fractional cent, the product is rounded half up. Two rounding disciplines matter and are not interchangeable. The monthly benefit allocation applies a single final rounding: the full product of base amount, tier multiplier, and urgency multiplier is rounded half up once, at the end, to integer cents. The Double-Up match, by contrast, rounds each produce-eligible line individually and then sums the rounded line matches; rounding the unrounded sum instead yields different numbers and is not permitted. A1c measurements are compared at one decimal place.

### 2.7. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control, and both guard an aggregate whose version can be advanced by a superseding creation. Creating a renewal against an enrollment requires the request to carry `expected_enrollment_version`, holding the enrollment's `version` as the client last observed it; if another writer has advanced the enrollment's version since then — which happens precisely when a renewal creation supersedes a prior draft renewal — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Creating a funder report under a program likewise requires `expected_program_version` matching the program's current `version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412), which is how the API protects a client from unknowingly replacing a report another writer just created for the same pool and period. Each successful creation of either kind increments the parent entity's `version` by one. No other endpoint accepts a version field.

### 2.8. Pool Ledgers and Reserve Accounting

Each funding pool is a small ledger with four balances. `committed_cents` is the amount a funder has committed to the pool; `disbursed_cents` is the sum of `voucher_applied_cents` over settled, non-voided redemptions of the program's vouchers; `reserved_cents` is the sum of `remaining_cents` over the program's vouchers still in ISSUED status; and `available_cents` is whatever is left — the committed amount minus disbursed minus reserved. Issuance moves money from available into reserved; settlement moves it from reserved into disbursed; voucher expiry and voucher voiding release it from reserved back into available. A funder's total exposure is capped: the sum of `committed_cents` across all of a funder's pools must never exceed that funder's `total_commitment_cents`, and a pool creation that would breach the cap is rejected with `ERR_COMMITMENT_EXCEEDED` (HTTP 422).

Alongside the pool ledger, each program keeps a Double-Up ledger: `double_up_pool_cents` is the total incentive budget configured at creation, `double_up_matched_cents` accumulates the match granted by settled, non-voided redemptions, and `double_up_remaining_cents` is the budget minus the matched sum. A new program starts with `double_up_matched_cents` at zero and `double_up_remaining_cents` equal to `double_up_pool_cents`.

### 2.9. Cascading Status Consistency

Status changes propagate down the funding hierarchy in a strict chain, and every cascade refreshes `updated_at` and increments `version` on each entity it touches. Suspending a funder moves each of that funder's FUNDED pools to SUSPENDED; each pool suspension, when it leaves its program with no remaining FUNDED pool, freezes the program to FROZEN — though only an ACTIVE program freezes, a DRAFT program being left unchanged — and the freeze in turn suspends every one of that program's enrollments currently in ACTIVE status. Reinstating the funder walks the chain back only partway: its SUSPENDED pools return to FUNDED, and a FROZEN program that regains a FUNDED pool returns to ACTIVE — but the suspended enrollments stay SUSPENDED. That asymmetry is deliberate: enrollment reinstatement is a separate, manual act by a `ProgramAdmin`. Funding an individual PENDING pool of a FROZEN program triggers the same unfreeze. Program closure cascades to terminal enrollment states, and benefit-cycle closure expires the cycle's outstanding vouchers and releases their reserves; §3 details each of those flows where they occur.

### 2.10. Request Validation Order

When several checks could reject the same request, the server applies them in a fixed priority order so the surfaced error is deterministic. First, authentication: the `X-User-Role` and `X-User-ID` headers must be present and the role must be a declared role, otherwise `ERR_UNAUTHENTICATED`. Second, authorization: the role must be allowed on the endpoint and entity-backed ownership must hold — a `ClinicStaff` caller's clinic must match the resource's clinic, a `RetailerStaff` caller's retailer must match, a `FunderAnalyst` caller's funder scope must hold, and a `Participant` reads only their own records — otherwise `ERR_FORBIDDEN`. Third, existence: every referenced id must resolve — path parameters first, validated left to right, then body foreign keys in payload order — otherwise `ERR_NOT_FOUND`; a referenced id whose value is not a string is instead a shape failure, `ERR_VALIDATION`. Fourth, shape: required fields present and, for strings, non-empty; types correct; enum values within their declared sets; calendar-date fields well formed; and integer ranges respected (`household_size` at least 1, session `capacity` at least 1, `minutes_attended` strictly positive), otherwise `ERR_VALIDATION`. A redemption basket that is missing or not an array fails here as `ERR_VALIDATION`, while an empty basket or a malformed line — a non-object line, an unknown `category`, or a non-positive `amount_cents` — is rejected here as `ERR_INVALID_TENDER`, ahead of the state and cross-entity gates below. This is also where a duplicate `npi_number` or a duplicate `period_index` within a program is rejected. Fifth, optimistic concurrency: where an endpoint takes an `expected_enrollment_version` or `expected_program_version`, it must match the parent's current `version`, otherwise `ERR_STALE_VERSION`. Sixth, state preconditions: the target and parent entities must be in states that permit the transition — from-state membership, terminal lockdown, and the program, enrollment, referral, voucher, cycle, report, renewal, and session status gates — otherwise the appropriate state error among `ERR_INVALID_STATE`, `ERR_ALREADY_TERMINAL`, `ERR_PROGRAM_NOT_ACTIVE`, `ERR_PROGRAM_FROZEN`, `ERR_ENROLLMENT_NOT_ACTIVE`, `ERR_REFERRAL_NOT_REVIEWABLE`, `ERR_VOUCHER_NOT_REDEEMABLE`, `ERR_CYCLE_NOT_OPEN`, `ERR_CYCLE_ALREADY_OPEN`, `ERR_PRIOR_CYCLE_UNCLOSED`, `ERR_REPORT_NOT_EDITABLE`, `ERR_RENEWAL_NOT_ACTIONABLE`, or `ERR_SESSION_NOT_SCHEDULED`. Seventh, clinical safety: consent must be GRANTED for referral creation and approval and for biometric recording, and A1c values must be clinically plausible, otherwise `ERR_CONSENT_REVOKED` or `ERR_A1C_OUT_OF_RANGE`. Eighth, temporal rules: cycle and report windows must be well ordered, cycle periods must not overlap, session venues must be free within their buffer, and renewals must fall inside the renewal window, otherwise `ERR_INVALID_DATE_RANGE`, `ERR_PERIOD_OVERLAP`, `ERR_VENUE_CONFLICT`, or `ERR_OUTSIDE_RENEWAL_WINDOW`. Ninth, uniqueness and capacity: one non-terminal referral per patient and program, the clinic's active-referral cap, one enrollment per patient and program, one voucher per enrollment per cycle, session capacity, one completion per enrollment and session — otherwise `ERR_DUPLICATE_REFERRAL`, `ERR_CLINIC_REFERRAL_CAP`, `ERR_DUPLICATE_ENROLLMENT`, `ERR_SESSION_FULL`, `ERR_DUPLICATE_COMPLETION`, or `ERR_VALIDATION`. Tenth, cross-entity state gates: the clinic must be ACTIVE for referral, patient, and biometric writes; the retailer must be ACTIVE for redemptions; a FUNDED pool must exist for issuance and for program activation; and a referral's clinic must match its patient's clinic — otherwise `ERR_CLINIC_SUSPENDED`, `ERR_RETAILER_SUSPENDED`, `ERR_POOL_NOT_FUNDED`, `ERR_NO_FUNDED_POOL`, or `ERR_PATIENT_CLINIC_MISMATCH`. Eleventh and last, fiscal rules: the funder commitment cap, voids only while funds are not finalized, and pool closure only with zero reserves — otherwise `ERR_COMMITMENT_EXCEEDED`, `ERR_VOID_NOT_ALLOWED`, or `ERR_POOL_BUSY`.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Program: Funders, Pools, Clinics, and Retailers

A program begins life in DRAFT when a `ProgramAdmin` creates it with its `name`, its window (`start_date` inclusive, `end_date` exclusive, both calendar dates), and its economic configuration: `base_monthly_benefit_cents` for a household of one, `household_increment_cents` added per additional member, the `max_household_size` cap used in benefit computation, the Double-Up knobs `double_up_multiplier`, `double_up_daily_cap_cents`, and `double_up_pool_cents`, the engagement thresholds `tier2_completions` and `tier3_completions`, the `renewal_window_days` grace period, and the `outcome_improvement_threshold` that defines a meaningful A1c drop. At creation the program's `status` is DRAFT, its Double-Up ledger is untouched — `double_up_matched_cents` zero, `double_up_remaining_cents` equal to the full pool budget — and its `ops_run_index` starts at zero. The programs listing accepts an optional `status` filter.

Money enters through funders and pools. A `ProgramAdmin` registers a funder with its `name`, `contact_email`, and `total_commitment_cents`; the funder is ACTIVE immediately. Suspending a funder — an act requiring it to be ACTIVE, otherwise `ERR_INVALID_STATE` — moves it to SUSPENDED and sets off the cascade described in §2.9 — every FUNDED pool of that funder becomes SUSPENDED, any program left without a FUNDED pool becomes FROZEN, and that program's ACTIVE enrollments are suspended with it. Reinstating — from SUSPENDED only, otherwise `ERR_INVALID_STATE` — returns the funder to ACTIVE, returns its SUSPENDED pools to FUNDED, and unfreezes any FROZEN program — while the program's enrollments remain SUSPENDED until individually reinstated.

A funding pool is created in PENDING status against a `program_id` and a `funder_id` with a `committed_cents` amount; its ledger starts clean, with `disbursed_cents` and `reserved_cents` at zero and `available_cents` equal to the commitment. Pool creation is where the funder commitment cap bites: if the new commitment would push the funder's total committed across all pools past `total_commitment_cents`, the create fails with `ERR_COMMITMENT_EXCEEDED`. Only the pool's own funder may fund it — a `FunderAnalyst` whose `X-User-ID` equals the pool's `funder_id`, otherwise `ERR_FORBIDDEN` — and funding additionally requires the funder itself to be ACTIVE (otherwise `ERR_INVALID_STATE`) and the program to be in DRAFT, ACTIVE, or FROZEN (otherwise `ERR_PROGRAM_NOT_ACTIVE`). Funding moves the pool PENDING to FUNDED — a CLOSED pool rejects funding with `ERR_ALREADY_TERMINAL` and any other non-PENDING pool with `ERR_INVALID_STATE` — and, if the program was FROZEN, returns it to ACTIVE. An administrator closes a pool in FUNDED or SUSPENDED status only when its `reserved_cents` is exactly zero; any outstanding reserve rejects the close with `ERR_POOL_BUSY`, closing a CLOSED pool is `ERR_ALREADY_TERMINAL`, and closing a PENDING pool is `ERR_INVALID_STATE`. The funding-pool listing accepts optional `program_id` and `funder_id` filters.

Clinics and retailers are the program's two edges. A clinic is registered with its `name`, a nationally unique `npi_number` — a duplicate NPI across clinics is rejected with `ERR_VALIDATION` — and a `max_active_referrals` cap; it starts ACTIVE. Suspending a clinic moves it from ACTIVE — any other state rejects the act with `ERR_INVALID_STATE` — to SUSPENDED, and while suspended every new referral, patient registration, and biometric reading for that clinic is rejected with `ERR_CLINIC_SUSPENDED`; reinstatement, permitted only from SUSPENDED (else `ERR_INVALID_STATE`), restores ACTIVE. A retailer is registered with its `name`, its `kind` — one of GROCERY, FARMERS_MARKET, or MOBILE_MARKET — and a `double_up_eligible` flag governing whether the produce match applies at its tills. Suspending a retailer blocks new redemptions there with `ERR_RETAILER_SUSPENDED`; already-settled redemptions are unaffected. Suspend and reinstate require the retailer to be ACTIVE and SUSPENDED respectively, otherwise `ERR_INVALID_STATE`.

Activation and closure bracket the program's working life. Activation moves a program from DRAFT to ACTIVE and demands at least one FUNDED pool attached to it; without one the attempt fails with `ERR_NO_FUNDED_POOL`. Activation attempted on a CLOSED program is `ERR_ALREADY_TERMINAL`, and on a program in any other non-DRAFT state `ERR_INVALID_STATE`. Closure is permitted from ACTIVE or from FROZEN, requires that no benefit cycle of the program be OPEN (an open cycle rejects the close with `ERR_OPEN_CYCLES_EXIST`), and lands the program in its terminal CLOSED status with a final enrollment cascade: enrollments in ACTIVE or LAPSED become COMPLETED, while enrollments in SUSPENDED become TERMINATED. Closure attempted from DRAFT is `ERR_INVALID_STATE`, and from CLOSED `ERR_ALREADY_TERMINAL`.

### 3.2. Patients, Consent, and the Referral Pipeline

Clinic staff register patients at their own clinic: the payload's `clinic_id` must equal the acting `X-User-ID`, and a mismatch is `ERR_FORBIDDEN`. Registration captures `full_name`, `date_of_birth`, and `household_size`, which must be at least 1. A new patient's `consent_status` is PENDING. The owning clinic may grant consent — moving PENDING, or a previously REVOKED consent, to GRANTED — and may revoke a GRANTED consent back to REVOKED; both acts are ownership-checked against the patient's clinic, granting an already-GRANTED consent or revoking one that is not GRANTED is `ERR_INVALID_STATE`, and a revoked consent blocks new referrals and new biometric readings for that patient. The patients listing accepts an optional `clinic_id` filter, and a `Participant` may read only their own patient record.

A referral is the clinic's request to enroll a patient in a program. The submitting clinic supplies `clinic_id`, `patient_id`, `program_id`, an ICD-10 `diagnosis_code` such as E11.9, and a `priority` of STANDARD or URGENT. Submission is gated, in the order given by §2.10: the acting clinic must own the referral's clinic; the clinic must be ACTIVE, else `ERR_CLINIC_SUSPENDED`; the patient's consent must be GRANTED, else `ERR_CONSENT_REVOKED`; the referral's clinic must be the same clinic that manages the patient — a `clinic_id` that differs from the patient's own `clinic_id` is `ERR_PATIENT_CLINIC_MISMATCH`; at most one non-terminal referral may exist for the same patient and program, else `ERR_DUPLICATE_REFERRAL`; and the clinic's count of referrals sitting in SUBMITTED or UNDER_REVIEW must be below its `max_active_referrals`, else `ERR_CLINIC_REFERRAL_CAP`. A fresh referral lands in SUBMITTED with `appeal_count` at zero and `decision_reason`, `appeal_reason`, and `enrollment_id` all empty (null).

Review is the program operator's desk. Starting review moves SUBMITTED to UNDER_REVIEW. Approval — detailed in §3.3 — moves UNDER_REVIEW to APPROVED and creates the enrollment. Declining requires a `decision_reason` (a missing reason is `ERR_VALIDATION`) and moves the referral to DECLINED. Decline is not the end of the road: the owning clinic may appeal with an `appeal_reason` (again required, else `ERR_VALIDATION`; a foreign clinic is `ERR_FORBIDDEN`), which moves DECLINED back to UNDER_REVIEW and increments `appeal_count` by one — the loop may repeat without limit. The owning clinic may instead withdraw a referral from SUBMITTED or UNDER_REVIEW, landing it in WITHDRAWN. Review actions attempted on a referral in the wrong state are rejected with `ERR_REFERRAL_NOT_REVIEWABLE`, and any transition attempted from a terminal state — APPROVED, WITHDRAWN, or EXPIRED — is `ERR_ALREADY_TERMINAL`. Referrals can also die of old age: the operations run in §3.9 expires stale ones. The referrals listing accepts optional `clinic_id`, `patient_id`, `program_id`, and `enrollment_id` filters.

### 3.3. From Approval to Enrollment

Approval is the hinge of the whole pipeline, and it is heavily gated: the target program must be ACTIVE (otherwise `ERR_PROGRAM_NOT_ACTIVE`), the patient's consent must still be GRANTED (otherwise `ERR_CONSENT_REVOKED`), and no enrollment may already exist for the same patient and program in ACTIVE, SUSPENDED, or LAPSED status (otherwise `ERR_DUPLICATE_ENROLLMENT`). When all three hold, the referral becomes APPROVED and an enrollment is created in one motion: its `program_id` and `patient_id` are copied from the referral, its `referral_id` points back to the originating referral, its `household_size` is a snapshot of the patient's household size at approval time, its status starts ACTIVE, its `engagement_tier` starts at T1, its lifetime counters `lifetime_redeemed_cents` and `lifetime_match_cents` start at zero, and `lapsed_at` is empty. The referral's `enrollment_id` is set to the new enrollment. The approval response (HTTP 200) carries the updated referral object; the new enrollment is reached through the referral's `enrollment_id`.

From ACTIVE, an enrollment can be suspended by a `ProgramAdmin` — or automatically when its program freezes — landing in SUSPENDED. Reinstatement returns SUSPENDED to ACTIVE but is refused while the program is FROZEN (`ERR_PROGRAM_FROZEN`) or CLOSED (`ERR_PROGRAM_NOT_ACTIVE`). Termination is available from ACTIVE, SUSPENDED, or LAPSED and requires a `reason`; it lands the enrollment in TERMINATED. On the wrong from-state these actions are rejected uniformly: a terminal enrollment draws `ERR_ALREADY_TERMINAL`, and any other disallowed state — suspending a SUSPENDED or LAPSED enrollment, reinstating one that is not SUSPENDED, or terminating in a state outside the three named — draws `ERR_INVALID_STATE`. Program closure completes the two live paths — ACTIVE and LAPSED enrollments become COMPLETED — and terminates SUSPENDED ones. Both TERMINATED and COMPLETED are terminal. Redemptions and education completions demand an ACTIVE enrollment and reject anything else with `ERR_ENROLLMENT_NOT_ACTIVE`. The enrollments listing accepts optional `program_id`, `patient_id`, and `referral_id` filters.

### 3.4. Benefit Cycles and the Issuance Waterfall

Within a program, benefits are rationed into monthly cycles. An administrator creates a cycle — an act not gated on the program's status — with a `period_index` — unique within the program, with duplicates rejected as `ERR_VALIDATION` — plus a `start_date` and an `end_date`. The window is half-open: the start date is included, the end date is excluded. The start must precede the end and the whole window must lie within the program's own window, otherwise `ERR_INVALID_DATE_RANGE`; and the new period must not overlap any existing cycle of the program — exact adjacency, where one cycle's `end_date` equals another's `start_date`, is allowed — otherwise `ERR_PERIOD_OVERLAP`. A new cycle is SCHEDULED, and the cycles listing accepts an optional `program_id` filter.

Opening a cycle is sequential. Opening a CLOSED cycle is `ERR_ALREADY_TERMINAL`, and opening one already OPEN is `ERR_INVALID_STATE`. The program must be ACTIVE (`ERR_PROGRAM_NOT_ACTIVE` otherwise), no other cycle of the program may already be OPEN (`ERR_CYCLE_ALREADY_OPEN`), and every cycle of the program with a lower `period_index` must already be CLOSED (`ERR_PRIOR_CYCLE_UNCLOSED`). Closing a cycle — permitted only from OPEN, else `ERR_CYCLE_NOT_OPEN` — settles it: each voucher of the cycle still in ISSUED status is expired in `created_at` ascending order (ties broken by creation order), moving to EXPIRED, and each expiry releases that voucher's `remaining_cents` from the pool's `reserved_cents` back into `available_cents`.

Issuance is the waterfall that turns a cycle into vouchers. It runs only on an OPEN cycle (otherwise `ERR_CYCLE_NOT_OPEN`) and only when the program has a FUNDED pool (otherwise `ERR_POOL_NOT_FUNDED`); if several pools are FUNDED, the one with the earliest `created_at` (ties broken by creation order) funds the run. Candidates are the program's ACTIVE enrollments that do not already hold a voucher for this cycle — one voucher per enrollment per cycle is a hard invariant. They are considered in order of the enrollment's `created_at` ascending, ties broken by the originating referral's `created_at` ascending, and any further tie by the patient's `created_at` ascending, with any remaining tie broken by creation order. For each candidate, the face value is computed from the program's benefit formula: the household size used is the enrollment's `household_size` capped at the program's `max_household_size`; the base is `base_monthly_benefit_cents` plus one `household_increment_cents` for each household member beyond the first, up to that cap; the engagement tier then scales the base by 1.00 at T1, 1.10 at T2, or 1.25 at T3; and an originating referral whose `priority` is URGENT adds a further 1.10 multiplier, while STANDARD adds none. The full product is rounded half up once to whole cents to give `face_value_cents`. If the pool's `available_cents` covers the face value, a voucher is created in ISSUED status with `redeemed_cents` at zero and `remaining_cents` equal to `face_value_cents`, stamped with the recipient `enrollment_id` and the issuing `benefit_cycle_id`, and the face value moves from the pool's `available_cents` into its `reserved_cents`. If the pool cannot cover it, the enrollment is skipped — its id is recorded in `skipped_enrollment_ids` — and the waterfall continues to the next candidate rather than aborting. The run reports `issued_count`, `total_face_value_cents`, and `skipped_enrollment_ids`, and refreshes the funding pool's `updated_at` and `version` even when nothing is issued. Because only enrollments without a voucher for the cycle are considered, re-running issuance on the same cycle issues nothing new to prior recipients.

Vouchers then live a short, well-defined life. A redemption that drains a voucher to exactly zero remaining cents moves it from ISSUED to EXHAUSTED; if a later void of that redemption restores value, the voucher returns from EXHAUSTED to ISSUED. Cycle close expires ISSUED vouchers as described above. An administrator may void an ISSUED voucher outright — a `reason` is required — moving it to VOIDED and releasing its `remaining_cents` from the pool's reserve back to available. Any voucher operation attempted on a voucher no longer in ISSUED status is rejected with `ERR_VOUCHER_NOT_REDEEMABLE`. The vouchers listing accepts optional `enrollment_id` and `benefit_cycle_id` filters.

### 3.5. Redemption at the Market and the Double-Up Match

At the till, a `RetailerStaff` cashier creates a redemption. The payload's `retailer_id` must equal the acting `X-User-ID` — anything else is `ERR_FORBIDDEN` — and names the redeeming `enrollment_id` plus the basket as `lines`, a non-empty array in which each line carries a `category` of PRODUCE_ELIGIBLE, STAPLE, or OTHER and a strictly positive integer `amount_cents`. An empty basket, a non-positive amount, or an unknown category is rejected with `ERR_INVALID_TENDER`. The retailer must be ACTIVE (`ERR_RETAILER_SUSPENDED` otherwise) and the enrollment must be ACTIVE (`ERR_ENROLLMENT_NOT_ACTIVE` otherwise). A new redemption is born SETTLED, with `redeemed_at` stamped from the logical clock.

The Double-Up match is computed in a pinned order. First, per line: for each line whose `category` is PRODUCE_ELIGIBLE, the line's match is its `amount_cents` multiplied by the program's `double_up_multiplier`, rounded half up to whole cents — the raw match is the sum of these per-line rounded matches, and rounding the unrounded sum instead is forbidden. The redemption's `produce_eligible_cents` is the unrounded sum of the PRODUCE_ELIGIBLE line amounts. Second, caps: if the retailer's `double_up_eligible` flag is false, `match_cents` is zero regardless; otherwise `match_cents` is the smallest of the raw match, the enrollment's remaining daily match allowance, and the program's `double_up_remaining_cents`. The daily allowance is the program's `double_up_daily_cap_cents` minus the sum of `match_cents` over the enrollment's SETTLED redemptions whose `redeemed_at` falls on the current UTC calendar date per the logical clock. The cap is inclusive at the boundary — a redemption that brings the day's matched total exactly to the cap is allowed — and hitting a cap clamps the match to the remaining amount rather than producing an error. The computed match is floored at zero: when every allowance is exhausted, the match is simply zero.

Third, the tender split, also in pinned order. The `subtotal_cents` is the sum of every line's `amount_cents`. The voucher drawn is the enrollment's oldest ISSUED voucher, ordered by `created_at` ascending (ties broken by creation order). The `voucher_applied_cents` is the smaller of that voucher's `remaining_cents` and the subtotal minus the match, floored at zero — it is zero both when no ISSUED voucher exists and when the match alone covers the subtotal. Whenever the applied amount is zero the redemption's `voucher_id` is left empty; otherwise `voucher_id` records the voucher actually debited. Whatever is left is the patient's own money: `patient_pay_cents` equals the subtotal minus the match minus the voucher-applied amount.

Settlement ripples through four ledgers at once. The debited voucher's `redeemed_cents` grows by the applied amount, and if its `remaining_cents` reaches exactly zero it becomes EXHAUSTED. The funding pool's `disbursed_cents` grows by the applied amount while its `reserved_cents` shrinks by the same. The program's Double-Up ledger absorbs the match: `double_up_matched_cents` grows by `match_cents` and `double_up_remaining_cents` shrinks by it. And the enrollment's `lifetime_redeemed_cents` and `lifetime_match_cents` grow by the applied and matched amounts respectively. A settlement leg whose amount is zero leaves its ledger untouched: the voucher and pool move only when the applied amount is positive, the Double-Up ledger only when the match is positive, and the enrollment's lifetime counters only when at least one of the two is positive.

Voiding unwinds all of it, and is available to the cashier's own retailer or to a `ProgramAdmin`, with a mandatory `reason`. A void is allowed only while the money is still in flight: the benefit cycle of the debited voucher must still be OPEN, otherwise `ERR_VOID_NOT_ALLOWED`; a redemption whose `voucher_id` is empty — nothing was drawn from any voucher — may be voided while the enrollment's program is not CLOSED; and an already-VOIDED redemption rejects a second void with `ERR_VOID_NOT_ALLOWED`. The compensation is exact: the voucher's `redeemed_cents` is reduced by the applied amount, returning it from EXHAUSTED to ISSUED if its remaining cents become positive again; the pool's `disbursed_cents` is reduced by the applied amount and its `reserved_cents` increased by it, since the voucher stands ISSUED once more; the program's `double_up_matched_cents` is reduced by the match and `double_up_remaining_cents` restored; and the enrollment's `lifetime_redeemed_cents` and `lifetime_match_cents` are reduced by the applied and matched amounts. The redemptions listing accepts optional `retailer_id`, `enrollment_id`, and `voucher_id` filters.

### 3.6. Nutrition Education and Engagement Tiers

Programs pair the benefit with nutrition education. A `ProgramAdmin` or an `Educator` schedules a session under a program — scheduling is not gated on the program's status — with a `topic`, a `venue`, a `starts_at` and `ends_at` — the end must fall after the start, with a misordered window rejected as `ERR_INVALID_DATE_RANGE` — a `capacity` of at least 1, and an `educator_ref` recording the responsible educator for audit: when an `Educator` schedules, `educator_ref` is set from the acting `X-User-ID` and any payload value is ignored, while a `ProgramAdmin` must supply `educator_ref` in the payload (a missing one is `ERR_VALIDATION`). Venues are scarce within a program: a new session conflicts when its venue is already occupied by another session of the same program whose time window, extended by a thirty-minute buffer on each side, strictly overlaps the new one — a window that merely touches the buffered boundary does not conflict, and CANCELLED sessions do not occupy their venue — and the conflict is rejected with `ERR_VENUE_CONFLICT`. A new session is SCHEDULED; the sessions listing accepts an optional `program_id` filter.

The educator then runs the session and either marks it completed — SCHEDULED to COMPLETED, after which completions may be recorded — or cancels it, SCHEDULED to CANCELLED. Either action on a session that is not SCHEDULED is rejected with `ERR_SESSION_NOT_SCHEDULED`.

Recording a completion is the educator's roll call on a COMPLETED session — a session in any other state rejects the write with `ERR_SESSION_NOT_SCHEDULED`. The payload names the `enrollment_id`, the `minutes_attended` (strictly positive), and whether the attendee `passed`. The enrollment must be ACTIVE, else `ERR_ENROLLMENT_NOT_ACTIVE`; the session must still have room — when its recorded completions already equal its `capacity`, the write fails with `ERR_SESSION_FULL`; and each enrollment may be recorded against a given session only once, else `ERR_DUPLICATE_COMPLETION`. A completion row is immutable: it carries only `id` and `created_at` alongside its fields, with no `updated_at` or `version`. The completions listing accepts optional `enrollment_id` and `session_id` filters.

Every recorded completion recomputes the enrollment's engagement tier, and the enrollment's `updated_at` and `version` are refreshed only when the recomputed tier differs from the current one. The count that matters is the number of that enrollment's completion rows with `passed` true — sessions in any status contribute, but only passed completions count. If the count is at least the program's `tier3_completions`, the tier is T3; otherwise, if it is at least `tier2_completions`, the tier is T2; otherwise it remains T1. Reaching a threshold exactly promotes the enrollment. The tier is not decorative: it feeds the 1.00, 1.10, and 1.25 multipliers at issuance time in §3.4.

### 3.7. Biometric Outcomes and the A1c Measure

Clinic staff record biometric readings against an enrollment of their own clinic. Each reading has a `kind` — A1C, WEIGHT_KG, or SYSTOLIC_BP — a numeric `value`, a `measured_at` timestamp that may legitimately precede the moment of recording, and a `source` of CLINIC, LAB_VERIFIED, or SELF_REPORT. Three gates apply: the patient's clinic must be ACTIVE (`ERR_CLINIC_SUSPENDED`), the patient's consent must be GRANTED (`ERR_CONSENT_REVOKED`), and an A1C `value` must be clinically plausible — within the range 3.0 to 20.0 inclusive — with anything outside rejected as `ERR_A1C_OUT_OF_RANGE`. Readings are immutable once written, carrying only `id` and `created_at`, and the readings listing accepts an optional `enrollment_id` filter.

Outcome measurement asks a simple question per enrollment: did A1c fall enough? For each enrollment of the program in ACTIVE, SUSPENDED, or LAPSED status, the baseline is the `value` of the A1C reading with the earliest `measured_at`, ties broken by `created_at` ascending, and the latest reading is the one with the latest `measured_at`, with ties again broken by `created_at` ascending and any remaining tie broken by creation order. Two variants then answer the question differently. The inclusive variant considers readings of every source: with at least two readings, the delta is the latest value minus the baseline value, and the enrollment counts as improved exactly when the delta is less than or equal to the negative of the program's `outcome_improvement_threshold`, compared at one decimal place. The verified variant restricts both endpoints to readings whose `source` is LAB_VERIFIED and applies the same delta and threshold; an enrollment with fewer than two lab-verified readings is never counted as improved under this variant, so the same raw data can yield a different improved set. Which variant surfaces where is decided by context: the program summary in §3.9 publishes both counts side by side, while a funder report carries the count selected by its `basis`.

### 3.8. Lapse, Renewal, and the End of an Enrollment

Benefits that go untouched eventually lapse. During an operations run (§3.9), the server looks at the program's CLOSED benefit cycle with the highest `period_index`; every ACTIVE enrollment holding at least one voucher in that cycle whose total `redeemed_cents` across those vouchers is exactly zero has failed to engage, and moves to LAPSED with `lapsed_at` set to the current logical clock.

Renewal is the clinic's way back. A `ClinicStaff` member of the clinic that owns the enrollment's patient — anyone else is `ERR_FORBIDDEN` — may create a renewal for an enrollment in ACTIVE or LAPSED status; any other enrollment status rejects the creation with `ERR_RENEWAL_NOT_ACTIONABLE`. For a LAPSED enrollment there is a clock on the wall: creation must happen within the program's `renewal_window_days` after `lapsed_at`, and a later attempt is `ERR_OUTSIDE_RENEWAL_WINDOW`; the boundary is inclusive, so creation exactly `renewal_window_days` after `lapsed_at` still succeeds. The request records a free-text `reason` and must carry `expected_enrollment_version` matching the enrollment's current `version`, per §2.7; a mismatch is `ERR_STALE_VERSION` (HTTP 412). A successful creation increments the enrollment's `version` by one and supersedes any prior DRAFT renewal of the same enrollment, moving it to SUPERSEDED. The new renewal starts in DRAFT with `resubmit_count` at zero and `denial_reason` empty (null), and the renewals listing accepts an optional `enrollment_id` filter.

From DRAFT, the owning clinic submits the renewal, moving it to SUBMITTED. A `ProgramAdmin` then adjudicates. Approval requires the patient's clinic to be ACTIVE — a suspended clinic blocks approval with `ERR_CLINIC_SUSPENDED` — and moves the renewal to APPROVED; when the underlying enrollment is LAPSED, approval reactivates it to ACTIVE, clears `lapsed_at` to empty, and increments the enrollment's `version`. Denial requires a `denial_reason` (missing it is `ERR_VALIDATION`) and lands the renewal in DENIED. Denial is not final: the owning clinic may resubmit with a fresh `reason`, moving DENIED back to SUBMITTED and incrementing `resubmit_count` by one, and this loop may repeat; the fresh `reason` is written to the renewal even when the resubmit itself is rejected for being in the wrong state. Any renewal transition attempted from the wrong state is `ERR_RENEWAL_NOT_ACTIONABLE`. Separately, an administrator may always terminate an enrollment outright as described in §3.3, and program closure in §3.1 ends every enrollment that remains.

### 3.9. Funder Reporting, Operations Runs, and Program Close-Out

Reporting follows a strict segregation of duties: the `ProgramAdmin` compiles and submits reports, and only the funder whose money is being reported on may adjudicate them. Creating a report under a program — an act not gated on the program's status — names the `funding_pool_id` — which must be a pool of that very program, a mismatch rejected as `ERR_VALIDATION` — a `period_start` and `period_end`, and a `basis` of ACCRUAL or CASH. The period is a half-open window of UTC dates: a redemption whose `redeemed_at` date equals `period_start` is included, while one equal to `period_end` is excluded, and a window whose start does not precede its end is `ERR_INVALID_DATE_RANGE`. The request must also carry `expected_program_version` matching the program's current `version`, per §2.7, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412); a successful creation increments the program's `version` by one and supersedes any prior DRAFT or RETURNED report for the same pool and period, moving it to SUPERSEDED.

Every metric on the report is frozen at creation. `utilization_cents` depends on the basis: under ACCRUAL it is the pool's `disbursed_cents` plus its `reserved_cents` — issued-but-unredeemed value counts as utilized — while under CASH it is `disbursed_cents` alone, counting only settled disbursements. `total_redeemed_cents` sums `voucher_applied_cents` over SETTLED, non-voided redemptions of the program's enrollments — including redemptions that drew on no voucher — within the window, and `total_match_cents` sums their `match_cents` over the same set. `active_enrollments` counts the program's enrollments in ACTIVE status at creation time. `a1c_improved_count` selects its variant by basis: ACCRUAL reports the inclusive count, CASH reports the lab-verified count. A new report starts in DRAFT with `revision_count` at zero and `return_reason` empty (null), and the reports listing accepts optional `program_id` and `funding_pool_id` filters.

Adjudication is a loop. The administrator submits a report from DRAFT or from RETURNED, moving it to SUBMITTED. The pool's own funder — a `FunderAnalyst` whose `X-User-ID` equals the reported pool's `funder_id`, anyone else drawing `ERR_FORBIDDEN` — may accept it, landing it in the terminal ACCEPTED state, or return it with a mandatory `return_reason` (missing it is `ERR_VALIDATION`), which moves it to RETURNED and increments `revision_count` by one, ready for resubmission. Any of these actions attempted on a report in the wrong state is rejected with `ERR_REPORT_NOT_EDITABLE`.

The operations run is the program's periodic housekeeping, triggered by a `ProgramAdmin` advancing the operations epoch; it is not gated on the program's status. It increments the program's `ops_run_index` by one, expires referrals, and lapses disengaged enrollments. Referral expiry looks at every referral of the program in SUBMITTED or UNDER_REVIEW: one whose age — the current logical clock minus its `created_at` — is strictly greater than fourteen days moves to EXPIRED, while a referral exactly fourteen days old is not yet expired. Enrollment lapse applies the zero-redemption rule of §3.8 against the program's latest CLOSED cycle. The run answers with the new `ops_run_index` plus `expired_referral_count` and `lapsed_enrollment_count` tallies.

Finally, the program summary gives operators and funders a live posture readout — readable by any `ProgramAdmin` or `FunderAnalyst` without funder-ownership scoping: the pool ledger rollup `committed_cents`, `reserved_cents`, `disbursed_cents`, and `available_cents`, each summed over all of the program's pools whatever their status; the Double-Up ledger `double_up_matched_cents` and `double_up_remaining_cents`; the `active_enrollment_count`, counting only ACTIVE enrollments; the tier distribution `tier_t1_count`, `tier_t2_count`, and `tier_t3_count`, counted over the program's enrollments in ACTIVE, SUSPENDED, or LAPSED status; and both A1c outcome counts, `a1c_improved_inclusive_count` and `a1c_improved_verified_count`, computed as §3.7 describes. When the program's work is done, closure follows §3.1: no OPEN cycles may remain, the program lands in CLOSED, and its remaining enrollments complete or terminate as described there.

## 4. Endpoint Definitions

The API is mounted at the root path. Endpoints that create a new resource return HTTP 201 with the created resource; reads, state transitions, computations, and other modifications return HTTP 200. All responses use the envelope of §2.2, all list endpoints paginate per §2.3, and every endpoint enforces the validation order of §2.10. Request bodies, preconditions, and side effects are specified by the workflows in §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the logical clock to a supplied instant | ProgramAdmin |
| POST | `/programs` | Create a program (DRAFT) | ProgramAdmin |
| GET | `/programs/{programId}` | Get a program | ProgramAdmin, FunderAnalyst, ClinicStaff |
| GET | `/programs` | List programs, optional status filter | ProgramAdmin, FunderAnalyst, ClinicStaff |
| POST | `/programs/{programId}/activate` | Activate a DRAFT program; requires at least one FUNDED pool | ProgramAdmin |
| POST | `/programs/{programId}/close` | Close a program; requires no OPEN cycles | ProgramAdmin |
| POST | `/programs/{programId}/run-ops` | Advance the operations epoch: expire stale referrals, lapse inactive enrollments | ProgramAdmin |
| GET | `/programs/{programId}/summary` | Computed program posture: pool ledger rollup, Double-Up pool, tier distribution, A1c outcome counts | ProgramAdmin, FunderAnalyst |
| POST | `/funders` | Create a funder (ACTIVE) | ProgramAdmin |
| GET | `/funders/{funderId}` | Get a funder | ProgramAdmin, FunderAnalyst |
| POST | `/funders/{funderId}/suspend` | Suspend a funder; cascades pool to program to enrollment | ProgramAdmin |
| POST | `/funders/{funderId}/reinstate` | Reinstate a suspended funder; pools restore, programs unfreeze, enrollments stay SUSPENDED | ProgramAdmin |
| POST | `/funding-pools` | Create a funding pool (PENDING); commitment cap enforced per funder | ProgramAdmin |
| GET | `/funding-pools/{poolId}` | Get a funding pool | ProgramAdmin, FunderAnalyst |
| GET | `/funding-pools` | List funding pools with optional filters | ProgramAdmin, FunderAnalyst |
| POST | `/funding-pools/{poolId}/fund` | Fund a PENDING pool; only the pool's own funder may fund | FunderAnalyst |
| POST | `/funding-pools/{poolId}/close` | Close a pool; requires zero reserved cents | ProgramAdmin |
| POST | `/clinics` | Create a clinic (ACTIVE) | ProgramAdmin |
| GET | `/clinics/{clinicId}` | Get a clinic | ProgramAdmin, ClinicStaff |
| POST | `/clinics/{clinicId}/suspend` | Suspend a clinic | ProgramAdmin |
| POST | `/clinics/{clinicId}/reinstate` | Reinstate a clinic | ProgramAdmin |
| POST | `/retailers` | Create a retailer (ACTIVE) | ProgramAdmin |
| GET | `/retailers/{retailerId}` | Get a retailer | ProgramAdmin, RetailerStaff |
| POST | `/retailers/{retailerId}/suspend` | Suspend a retailer | ProgramAdmin |
| POST | `/retailers/{retailerId}/reinstate` | Reinstate a retailer | ProgramAdmin |
| POST | `/patients` | Register a patient at the acting clinic (consent PENDING) | ClinicStaff |
| GET | `/patients/{patientId}` | Get a patient | ProgramAdmin, ClinicStaff, Participant |
| GET | `/patients` | List patients with optional clinic filter | ProgramAdmin, ClinicStaff |
| POST | `/patients/{patientId}/grant-consent` | Grant consent (PENDING or REVOKED to GRANTED) | ClinicStaff |
| POST | `/patients/{patientId}/revoke-consent` | Revoke consent (GRANTED to REVOKED) | ClinicStaff |
| POST | `/referrals` | Submit a referral (SUBMITTED); clinic cap, consent, duplicate and clinic-match gates apply | ClinicStaff |
| GET | `/referrals/{referralId}` | Get a referral | ProgramAdmin, ClinicStaff |
| GET | `/referrals` | List referrals with optional filters | ProgramAdmin, ClinicStaff |
| POST | `/referrals/{referralId}/start-review` | Move referral SUBMITTED to UNDER_REVIEW | ProgramAdmin |
| POST | `/referrals/{referralId}/approve` | Approve a referral; creates the enrollment | ProgramAdmin |
| POST | `/referrals/{referralId}/decline` | Decline a referral under review | ProgramAdmin |
| POST | `/referrals/{referralId}/appeal` | Appeal a declined referral back into review (cyclic) | ClinicStaff |
| POST | `/referrals/{referralId}/withdraw` | Withdraw a referral in SUBMITTED or UNDER_REVIEW | ClinicStaff |
| GET | `/enrollments/{enrollmentId}` | Get an enrollment | ProgramAdmin, ClinicStaff, Participant |
| GET | `/enrollments` | List enrollments with optional filters | ProgramAdmin, ClinicStaff, Participant |
| POST | `/enrollments/{enrollmentId}/suspend` | Suspend an ACTIVE enrollment | ProgramAdmin |
| POST | `/enrollments/{enrollmentId}/reinstate` | Reinstate a SUSPENDED enrollment; blocked while program FROZEN | ProgramAdmin |
| POST | `/enrollments/{enrollmentId}/terminate` | Terminate an enrollment in ACTIVE, SUSPENDED, or LAPSED | ProgramAdmin |
| POST | `/programs/{programId}/cycles` | Create a benefit cycle (SCHEDULED); half-open non-overlap enforced, adjacency allowed | ProgramAdmin |
| GET | `/cycles/{cycleId}` | Get a benefit cycle | ProgramAdmin, FunderAnalyst, ClinicStaff |
| GET | `/cycles` | List benefit cycles with optional program filter | ProgramAdmin, FunderAnalyst, ClinicStaff |
| POST | `/cycles/{cycleId}/open` | Open a cycle; sequential gating on prior cycles | ProgramAdmin |
| POST | `/cycles/{cycleId}/issue` | Issue vouchers to eligible ACTIVE enrollments via the issuance waterfall | ProgramAdmin |
| POST | `/cycles/{cycleId}/close` | Close a cycle; expires ISSUED vouchers and releases reserves | ProgramAdmin |
| GET | `/vouchers/{voucherId}` | Get a voucher | ProgramAdmin, ClinicStaff, Participant |
| GET | `/vouchers` | List vouchers with optional filters | ProgramAdmin, ClinicStaff, Participant |
| POST | `/vouchers/{voucherId}/void` | Void an ISSUED voucher; releases its reserve back to the pool | ProgramAdmin |
| POST | `/redemptions` | Create and settle a redemption; computes Double-Up match and voucher tender split | RetailerStaff |
| GET | `/redemptions/{redemptionId}` | Get a redemption | ProgramAdmin, RetailerStaff, FunderAnalyst |
| GET | `/redemptions` | List redemptions with optional filters | ProgramAdmin, RetailerStaff, FunderAnalyst |
| POST | `/redemptions/{redemptionId}/void` | Void a settled redemption; full compensation of voucher, pool, Double-Up, and enrollment ledgers | RetailerStaff, ProgramAdmin |
| POST | `/programs/{programId}/education-sessions` | Schedule an education session; venue conflict with 30-minute buffer enforced | ProgramAdmin, Educator |
| GET | `/education-sessions/{sessionId}` | Get an education session | ProgramAdmin, Educator, ClinicStaff |
| GET | `/education-sessions` | List education sessions with optional program filter | ProgramAdmin, Educator, ClinicStaff |
| POST | `/education-sessions/{sessionId}/complete` | Mark a scheduled session completed | Educator |
| POST | `/education-sessions/{sessionId}/cancel` | Cancel a scheduled session | Educator |
| POST | `/education-sessions/{sessionId}/completions` | Record an enrollment's completion of a COMPLETED session; updates engagement tier | Educator |
| GET | `/education-completions/{completionId}` | Get an education completion | ProgramAdmin, Educator, ClinicStaff |
| GET | `/education-completions` | List education completions with optional filters | ProgramAdmin, Educator, ClinicStaff |
| POST | `/enrollments/{enrollmentId}/biometric-readings` | Record a biometric reading for an enrollment; consent and plausibility gates apply | ClinicStaff |
| GET | `/biometric-readings/{readingId}` | Get a biometric reading | ProgramAdmin, ClinicStaff |
| GET | `/biometric-readings` | List biometric readings with optional enrollment filter | ProgramAdmin, ClinicStaff |
| POST | `/programs/{programId}/funder-reports` | Create a funder report (DRAFT) with frozen metrics; supersedes prior DRAFT/RETURNED report for same pool and period; OCC on program version | ProgramAdmin |
| GET | `/funder-reports/{reportId}` | Get a funder report | ProgramAdmin, FunderAnalyst |
| GET | `/funder-reports` | List funder reports with optional filters | ProgramAdmin, FunderAnalyst |
| POST | `/funder-reports/{reportId}/submit` | Submit a DRAFT or RETURNED report | ProgramAdmin |
| POST | `/funder-reports/{reportId}/accept` | Accept a submitted report; only the pool's own funder | FunderAnalyst |
| POST | `/funder-reports/{reportId}/return` | Return a submitted report for revision; only the pool's own funder | FunderAnalyst |
| POST | `/enrollments/{enrollmentId}/renewals` | Create a renewal (DRAFT) for an ACTIVE or LAPSED enrollment; supersedes prior DRAFT renewal; OCC on enrollment version | ClinicStaff |
| GET | `/renewals/{renewalId}` | Get a renewal | ProgramAdmin, ClinicStaff |
| GET | `/renewals` | List renewals with optional enrollment filter | ProgramAdmin, ClinicStaff |
| POST | `/renewals/{renewalId}/submit` | Submit a DRAFT renewal | ClinicStaff |
| POST | `/renewals/{renewalId}/approve` | Approve a submitted renewal; reactivates a LAPSED enrollment | ProgramAdmin |
| POST | `/renewals/{renewalId}/deny` | Deny a submitted renewal | ProgramAdmin |
| POST | `/renewals/{renewalId}/resubmit` | Resubmit a denied renewal (cyclic) | ClinicStaff |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. The conditions that trigger each error are specified in the narratives of §2 and §3, alongside the workflows they guard.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 |
| `ERR_PROGRAM_FROZEN` | 409 |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 |
| `ERR_REFERRAL_NOT_REVIEWABLE` | 409 |
| `ERR_VOUCHER_NOT_REDEEMABLE` | 409 |
| `ERR_CYCLE_NOT_OPEN` | 409 |
| `ERR_CYCLE_ALREADY_OPEN` | 409 |
| `ERR_PRIOR_CYCLE_UNCLOSED` | 409 |
| `ERR_REPORT_NOT_EDITABLE` | 409 |
| `ERR_RENEWAL_NOT_ACTIONABLE` | 409 |
| `ERR_SESSION_NOT_SCHEDULED` | 409 |
| `ERR_CONSENT_REVOKED` | 422 |
| `ERR_A1C_OUT_OF_RANGE` | 422 |
| `ERR_CLINIC_SUSPENDED` | 409 |
| `ERR_RETAILER_SUSPENDED` | 409 |
| `ERR_POOL_NOT_FUNDED` | 409 |
| `ERR_NO_FUNDED_POOL` | 409 |
| `ERR_COMMITMENT_EXCEEDED` | 422 |
| `ERR_PERIOD_OVERLAP` | 409 |
| `ERR_VENUE_CONFLICT` | 409 |
| `ERR_INVALID_DATE_RANGE` | 400 |
| `ERR_OUTSIDE_RENEWAL_WINDOW` | 422 |
| `ERR_SESSION_FULL` | 409 |
| `ERR_DUPLICATE_COMPLETION` | 409 |
| `ERR_DUPLICATE_ENROLLMENT` | 409 |
| `ERR_DUPLICATE_REFERRAL` | 409 |
| `ERR_CLINIC_REFERRAL_CAP` | 409 |
| `ERR_INVALID_TENDER` | 422 |
| `ERR_VOID_NOT_ALLOWED` | 409 |
| `ERR_OPEN_CYCLES_EXIST` | 409 |
| `ERR_POOL_BUSY` | 409 |
| `ERR_PATIENT_CLINIC_MISMATCH` | 422 |
