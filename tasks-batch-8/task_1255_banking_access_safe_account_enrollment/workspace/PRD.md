# Banking Access & Safe Account Enrollment API — Product Requirements Document

## 1. Introduction

This document defines the product requirements for the Banking Access & Safe Account Enrollment API operated by a Bank On coalition. The system coordinates the full arc of an unbanked-access program: it certifies partner financial institutions against coalition account standards, routes participants referred by social-services agencies through documentation assistance and account-opening events, enforces a ChexSystems second-look barrier process when an applicant's prior banking record would otherwise disqualify them, pairs participants with financial-education coaches, tracks account retention at six and twelve months, and administers the funding grants and per-period partner reports that pay for the work.

The coalition serves populations that mainstream banking screens out: people whose only identity documents are a matrícula consular, a municipal ID, or a foreign passport; people with a flagged ChexSystems record from a past overdraft; people who have never had an account at all. The API therefore treats alternative-ID acceptance, second-look barrier negotiation, and education pairing as first-class workflows rather than exceptions, and it treats funding-grant money as a conserved ledger whose every cent of reservation and disbursement must be reconstructible from report activity. A logical clock, settable by coalition operations, drives every due-date, expiry, and follow-up evaluation so that scheduled sweeps are deterministic and reproducible.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API carries two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. The system recognizes five roles, spelled exactly as follows: `CoalitionAdmin`, `InstitutionOfficer`, `AgencyNavigator`, `Participant`, and `FinancialCoach`. A request missing either header, or presenting a role string outside this enumeration, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not authorized for the targeted endpoint, or that fails an entity-backed ownership check, is rejected with `ERR_UNAUTHORIZED_ROLE`.

Two roles are entity-backed. When `X-User-Role` is `InstitutionOfficer`, `X-User-ID` is the `id` of the acting `PartnerInstitution`; any ownership check on a resource that references an institution compares the resource's `institution_id` field to `X-User-ID`. When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting `Participant`; a barrier-case acceptance compares the case's `participant_id` field to `X-User-ID`. The remaining three roles carry opaque identifiers. When `X-User-Role` is `CoalitionAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example as `scored_by_user_id` or `finalized_by_user_id` on a `CertificationReview`, or `registered_by_user_id` on a `Participant`) but does not compare it to any entity's `id`. When `X-User-Role` is `AgencyNavigator`, `X-User-ID` is likewise opaque and may be recorded as `agency_user_id` on a `Referral` created through navigator intake. When `X-User-Role` is `FinancialCoach`, `X-User-ID` is an opaque coach identifier that is stored as `coach_id` on each `EducationPairing` the coach creates; completion and follow-up logging on a pairing compare the stored `coach_id` to the caller's `X-User-ID`.

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

List endpoints are paginated via the `limit` and `offset` query parameters. `limit` defaults to 10 when not supplied, accepts a minimum of 1 and a maximum of 100, and `offset` defaults to 0. All list endpoints return resources sorted by `created_at` in ascending order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every top-level resource carries a system-generated `id` formatted as a UUID with no type prefix, a `created_at` ISO 8601 UTC timestamp with three fractional digits marking creation, an `updated_at` ISO 8601 UTC timestamp refreshed on every mutation, and a `version` integer that increments by one on every mutation. Any write that changes a resource — including cascaded writes triggered by another resource's transition, computed-field refreshes, and ledger-anchor touches — updates `updated_at` and increments `version` on each resource actually mutated.

### 2.5. Logical Clock and Scheduled Evaluation Epoch

The server maintains a logical clock, separate from wall-clock time. At startup the logical clock reads exactly `2026-05-01T00:00:00Z`; before any explicit set call it never falls back to wall-clock time. A coalition administrator may advance the clock by supplying a `to_iso8601` timestamp; the clock is monotonic, and an attempt to set it to a value earlier than the current reading is rejected with `ERR_VALIDATION`. Every due-date, expiry, window-end, and follow-up rule in the system evaluates against this logical clock and only against it.

A single ops epoch capability, invocable by a `CoalitionAdmin`, sweeps four families of pending work in one run: it evaluates retention checkpoints whose `due_date` or `window_end` has been reached, lapses certifications whose `certification_expires_at` has passed, completes account-opening events whose `ends_at` has passed, and moves education pairings whose `follow_up_due_at` has been reached from `COMPLETED` to `FOLLOW_UP_DUE`. The epoch returns a summary object with integer counts `checkpoints_evaluated`, `certifications_lapsed`, `events_completed`, and `follow_ups_due`. Within a single epoch, retention checkpoints are processed in ascending `due_date` order, breaking ties by ascending `created_at`; ties are never broken by `id`.

### 2.6. Optimistic Concurrency Control on Parent Anchors

Two write endpoints carry optimistic-concurrency protection against a parent entity's version. Every other endpoint does not take a version field.

Creating a certification review requires the request to carry `expected_institution_version`, holding the `version` of the target `PartnerInstitution` as the client last observed it. Because a successful review creation supersedes the institution's live review and advances the institution's `version`, a create that arrives carrying the previously observed version is acting on a stale view of the institution; if the supplied value does not match the institution's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

Creating a partner report requires the request to carry `expected_grant_version`, holding the `version` of the target `FundingGrant` as the client last observed it. Because report creation advances the grant's `version` as a ledger-anchor touch, a create that arrives carrying the previously observed version is acting on a stale view of the grant's ledger state; if the supplied value does not match the grant's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.7. Monetary Values and Precision

All monetary amounts in the system are integer cents; no fractional cent ever appears on a resource or in a response. Rounding within calculations uses the round-half-up method. Where a computed rate is exposed as a decimal — the certification `weighted_score` and the report `retention_rate_m6` / `retention_rate_m12` fields — the precision is fixed per field: `weighted_score` is rounded half-up to two decimal places, and the retention rates are rounded half-up to four decimal places. Claim computation performs rounding per account before any summation, never once over a pre-summed total; the two orders produce different cents and the per-account order is the contract.

### 2.8. Conserved Quantities: Grant Ledger and Event Seats

Two invariants are observable at every instant. First, the funding-grant ledger conserves cents: for each `FundingGrant`, `available_cents` plus `reserved_cents` plus `disbursed_cents` always equals `total_cents`, including across the reservation release that compensates a rejected report and across the grant-suspend cascade. `reserved_cents` is the sum of `claim_total_cents` over the grant's reports in `SUBMITTED` status, `disbursed_cents` is the sum of `claim_total_cents` over its reports in `APPROVED` status, and `available_cents` is `total_cents` minus the other two. Second, event seats are conserved: an event's `booked_count` plus its remaining seats always equals `capacity`, and a book followed by an unbook restores `booked_count` exactly.

### 2.9. Nested and Cross-Referenced Resource Retrieval

Resource references are validated in a strict left-to-right order. Identifiers appearing in the URL path are resolved first, from the leftmost path parameter to the rightmost; the first identifier that does not correspond to an existing resource yields `ERR_NOT_FOUND` immediately. Only after every path identifier has resolved are body-carried foreign keys resolved, in the order the fields appear in the request payload, again surfacing `ERR_NOT_FOUND` on the first miss. A request that fails earlier auth or well-formedness checks never reaches this stage.

### 2.10. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed priority order so the surfaced error is deterministic. Authentication comes first — missing or malformed `X-User-ID` / `X-User-Role` headers surface `ERR_UNAUTHENTICATED` before anything else is examined. Authorization comes second — role-not-permitted and entity-backed ownership failures surface `ERR_UNAUTHORIZED_ROLE`. Body well-formedness is third — a malformed payload, missing required field, wrong type, or out-of-set enum value surfaces `ERR_VALIDATION`. Resource existence is fourth, per §2.9, surfacing `ERR_NOT_FOUND`. State-machine legality is fifth — a target resource not in a state from which the requested transition exists surfaces `ERR_INVALID_STATE`. Optimistic-concurrency staleness is sixth, surfacing `ERR_STALE_VERSION` on the two OCC-protected creates. Compliance gates come seventh (segregation of duties, documentation completeness, alternative-ID admissibility, barrier-resolution, education-required, follow-up-due), temporal conflicts eighth (event window overlap, review-gap, campaign overlap), cross-entity state ninth (institution certified, standard effective, grant active, referral consistency, event bookable, campaign active), and capacity, quota, and fiscal limits tenth (event full, coach caseload, claim cap, grant funds, campaign budget, pending claims, negotiation rounds, certification lapsed).

## 3. Business Logic & Workflows

### 3.1. Account Standards and the Certification Cycle

A `CoalitionAdmin` authors an **AccountStandard** by supplying a unique `code` (for example `BO-2026`), a human-readable `name`, the `effective_from` ISO date on which the standard takes effect, and the consumer-protection parameters the standard enforces: `monthly_fee_cap_cents` as the maximum allowable monthly maintenance fee, `overdraft_fee_allowed` to declare whether overdraft or NSF fees are permitted, `min_opening_deposit_cap_cents` as the maximum opening deposit an institution may require, `accepted_alt_id_types` naming which alternative identity documents the standard accepts as a subset of `MATRICULA_CONSULAR`, `MUNICIPAL_ID`, and `FOREIGN_PASSPORT`, `chex_second_look_required` to declare whether the standard mandates the second-look barrier process for ChexSystems-flagged applicants, `requires_financial_education` to declare whether account approval requires a completed education pairing for the participant, and `rubric_mode`, which is either `STANDARD_RUBRIC` or `REMEDIATION_RUBRIC` and selects the certification scoring thresholds used during reviews pinned to this standard. A new standard begins in `DRAFT` status.

Activating a standard moves it from `DRAFT` to `EFFECTIVE`; attempting to activate a standard not in `DRAFT` is rejected with `ERR_INVALID_STATE`. At most one standard is `EFFECTIVE` at any moment: activation automatically transitions whatever standard was previously `EFFECTIVE` to `SUPERSEDED`. Supersession never rewrites history — every `CertificationReview` already created keeps the `standard_id` it was pinned to at creation, so a review scored under an older rubric continues to be judged by that rubric even after the standard itself has been superseded.

Certification of a partner institution proceeds through a **CertificationReview**. A `CoalitionAdmin` opens a review by naming the `institution_id`, the `standard_id` to pin for the life of the review, the `period_start` and `period_end` ISO dates bounding the review window, and the OCC field `expected_institution_version` per §2.6. The pinned standard must be `EFFECTIVE`; opening a review against a standard in any other status is rejected with `ERR_STANDARD_NOT_EFFECTIVE`. The request requires `period_start` to be on or before `period_end`, with a violation surfaced as `ERR_VALIDATION`. Reviews for the same institution are spaced: excluding any review in `SUPERSEDED`, the new review's `period_start` must be at least thirty days after the latest prior review's `period_end`, with equality allowed; a tighter spacing is rejected with `ERR_REVIEW_GAP_VIOLATION`. The very first review for an institution carries no gap constraint. Opening a review also supersedes the institution's live review if one exists — a prior review still in `DRAFT` or `SCORED` moves to `SUPERSEDED` and can no longer be scored or finalized, with any further attempt rejected as `ERR_INVALID_STATE` — and the institution's `current_review_id` is set to the new review. On first review creation the institution moves from `APPLIED` to `UNDER_REVIEW`; a `LAPSED` institution likewise moves to `UNDER_REVIEW`; a `CERTIFIED` institution entering recertification also moves to `UNDER_REVIEW`, retaining its existing `certified_at` and `certification_expires_at` until the new review finalizes.

Scoring records the review's `criteria_ratings`: an array of `{criterion, rating}` pairs covering exactly the five criteria `FEE_COMPLIANCE`, `ACCESS`, `ALT_ID`, `CHEX_POLICY`, and `EDUCATION_SUPPORT`, each rating an integer from 0 to 4. A scoring request against a review not in `DRAFT` is rejected with `ERR_INVALID_STATE`; an incomplete criteria set or a rating outside 0..4 is rejected with `ERR_VALIDATION`. On scoring, the review moves from `DRAFT` to `SCORED`, the acting admin's opaque identifier is recorded as `scored_by_user_id`, and two computed fields materialize. The `weighted_score` is one hundred times the weighted sum of the ratings divided by four, rounded half-up to two decimal places, with criterion weights of 0.25 for `FEE_COMPLIANCE`, 0.20 for `ACCESS`, 0.15 for `ALT_ID`, 0.20 for `CHEX_POLICY`, and 0.20 for `EDUCATION_SUPPORT`. The `mandatory_floor_failed` flag is set to true when either the `FEE_COMPLIANCE` rating or the `CHEX_POLICY` rating is at most 1, and false otherwise.

Finalization is a separate act by a different administrator. Finalizing a review not in `SCORED` is rejected with `ERR_INVALID_STATE`. Segregation of duties is enforced: the finalizer's `X-User-ID` must differ from the recorded `scored_by_user_id`, and a matching finalizer is rejected with `ERR_SOD_VIOLATION`. The finalizer's identifier is recorded as `finalized_by_user_id`, the review's `outcome` is pinned, and the review lands in the matching terminal status. The outcome is computed from the rubric the review's pinned standard selects. Under `STANDARD_RUBRIC`, the outcome is `FAIL` when `mandatory_floor_failed` is true; otherwise `PASS` when the `weighted_score` is at least 90.00; otherwise `CONDITIONAL` when the score is at least 75.00; otherwise `FAIL`. Under `REMEDIATION_RUBRIC` the same floor applies, but the `PASS` threshold is 85.00 and the `CONDITIONAL` floor is 70.00, so an identical ratings set can land in a different band depending on the pinned rubric. A `PASS` outcome finalizes the review to `FINALIZED_PASS`, a `CONDITIONAL` outcome to `FINALIZED_CONDITIONAL`, and a `FAIL` outcome to `FINALIZED_FAIL`.

Finalization drives the institution. On `PASS` or `CONDITIONAL`, an institution in `UNDER_REVIEW` moves to `CERTIFIED`: `certified_at` is set to the current logical-clock reading, `certification_expires_at` is computed as `certified_at` plus twenty-four months, and `certified_standard_id` becomes the review's pinned `standard_id`. On `FAIL`, the institution moves from `UNDER_REVIEW` to `DECERTIFIED` and a four-link cascade runs: every `AccountOpeningEvent` of the institution still in `SCHEDULED` moves to `CANCELLED`; each cancelled event's referrals in `BOOKED` move back to `DOCS_COMPLETE` with their `booked_event_id` cleared; each affected participant's `pipeline_stage` is recomputed per §3.4; and the institution's `current_review_id` is cleared.

### 3.2. Partner Institutions: Suspension, Lapse, and Reinstatement

A `CoalitionAdmin` registers a **PartnerInstitution** with its `legal_name` and `charter_type` — either `BANK` or `CREDIT_UNION`. Registration lands the institution in `APPLIED` certification status with `certified_standard_id`, `certified_at`, and `certification_expires_at` all null, `accounts_opened_total` at zero, and `current_review_id` null.

A `CERTIFIED` institution can be suspended by a coalition administrator; attempting the transition from any other status is rejected with `ERR_INVALID_STATE`. While an institution is `SUSPENDED` or `LAPSED`, creation of new account applications for it is blocked with `ERR_INSTITUTION_NOT_CERTIFIED`. Suspension is reversible by reinstatement, but only while the certification has not yet lapsed: reinstatement requires the institution to be `SUSPENDED` (`ERR_INVALID_STATE` otherwise) and requires the current logical-clock reading to be strictly before `certification_expires_at`; a reinstatement attempted at or after expiry is rejected with `ERR_CERTIFICATION_LAPSED`. Lapse itself is not a manual act — when the ops epoch finds a `CERTIFIED` institution whose `certification_expires_at` has been reached by the logical clock, the institution moves to `LAPSED`. Both suspension and reinstatement increment the institution's `version`.

Institutions are listable with optional filters on `certification_status`, `certified_standard_id`, and `current_review_id`, alongside the standard pagination parameters.

### 3.3. Participants, Documentation, and Referral Intake

An `AgencyNavigator` or `CoalitionAdmin` registers a **Participant** with `full_name`, `date_of_birth`, `contact_zip`, and a self-reported `prior_banking_record` of `NONE`, `CLEAN`, or `FLAGGED` reflecting the intake view of the participant's ChexSystems posture. Registration may optionally include initial `id_documents`; the creating navigator or admin's opaque identifier is recorded as `registered_by_user_id`, and the participant lands in the `REGISTERED` pipeline stage.

Each entry of `id_documents` pairs a `doc_type` with a `status`. The recognized document types are `STATE_ID`, `SSN_CARD`, `ITIN_LETTER`, `MATRICULA_CONSULAR`, `MUNICIPAL_ID`, `FOREIGN_PASSPORT`, and `PROOF_OF_ADDRESS`; each entry's status is either `SUBMITTED` or `VERIFIED`. Documentation assistance is an ongoing activity: a navigator or admin updates the participant's `id_documents` through the documents-update capability, which upserts entries and then recomputes two derived fields. The `docs_complete` flag becomes true exactly when the participant holds at least one identity document — `STATE_ID`, `MATRICULA_CONSULAR`, `MUNICIPAL_ID`, or `FOREIGN_PASSPORT` — in `VERIFIED` status and also holds a `VERIFIED` `PROOF_OF_ADDRESS`. The `pipeline_stage` is then recomputed per §3.4.

A **Referral** connects a participant to the program's account-opening pipeline. Creation names the `participant_id` and a `created_via` of `NAVIGATOR` or `CAMPAIGN`. Navigator intake records the creating navigator's opaque identifier as `agency_user_id` and leaves `campaign_id` null; campaign intake requires `campaign_id` to name an `OutreachCampaign` and leaves `agency_user_id` null. Supplying a `campaign_id` on a `NAVIGATOR` referral, or omitting it on a `CAMPAIGN` referral, is a validation failure. A campaign-named referral additionally requires the campaign to still be `ACTIVE`; referencing a `CLOSED` campaign is rejected with `ERR_INVALID_STATE`. A new referral lands in `DOCS_PENDING`, and the participant's `pipeline_stage` is recomputed. Referrals are listable with optional filters on `participant_id`, `campaign_id`, `booked_event_id`, and `status`.

### 3.4. The Participant Pipeline Derivation

A participant's `pipeline_stage` is never written directly. It is recomputed whenever any of the participant's referrals or applications changes status, and whenever the participant's documents are updated, by taking the first matching rule in a fixed precedence. If any of the participant's applications is `OPENED`, the stage is `ACCOUNT_OPENED`. Otherwise, if any application is `SUBMITTED` or `REINSTATED`, the stage is `APPLIED`. Otherwise, if any referral is `BOOKED`, the stage is `EVENT_BOOKED`. Otherwise, if `docs_complete` is true, the stage is `DOCS_READY`. Otherwise, if any referral is `DOCS_PENDING` or `DOCS_COMPLETE`, the stage is `REFERRED`. Otherwise the stage is `REGISTERED`.

### 3.5. Account-Opening Events and Booking

An `InstitutionOfficer` schedules an **AccountOpeningEvent** by supplying the `institution_id` of their own institution — a mismatch between the acting officer's identity and the supplied `institution_id` is rejected with `ERR_UNAUTHORIZED_ROLE` — together with a `venue_code` identifying the branch or venue, the `starts_at` and `ends_at` timestamps bounding the event window, the `capacity` as the maximum concurrent bookings, and an `alt_id_accepted` flag declaring whether alternative identification will be accepted at this event. The window is half-open: it includes `starts_at` and excludes `ends_at`. A `starts_at` not strictly before `ends_at` is rejected with `ERR_VALIDATION`. The institution must be `CERTIFIED` at scheduling time, else `ERR_INSTITUTION_NOT_CERTIFIED`. Setting `alt_id_accepted` to true requires the institution's certified standard to accept at least one alternative ID type in its `accepted_alt_id_types`. Two events at the same institution and `venue_code` may not overlap: a new event conflicts with an existing `SCHEDULED` event when the new `starts_at` falls before the existing `ends_at` and the existing `starts_at` falls before the new `ends_at`, surfacing `ERR_EVENT_WINDOW_CONFLICT`; because windows are half-open, adjacency — one event's `starts_at` exactly equal to another's `ends_at` — does not conflict. A new event lands in `SCHEDULED` with `booked_count` zero.

Booking is the navigator's act of moving a referral from `DOCS_COMPLETE` to `BOOKED` against a named `event_id`. Before booking, the referral must have been advanced from `DOCS_PENDING` to `DOCS_COMPLETE` via the docs-complete capability, which requires the referral to be `DOCS_PENDING` (`ERR_INVALID_STATE` otherwise) and the participant's `docs_complete` to be true — a participant still missing verified documents yields `ERR_DOCS_INCOMPLETE`. The booking itself requires the referral to be `DOCS_COMPLETE`, the target event to be `SCHEDULED` (`ERR_EVENT_NOT_BOOKABLE` otherwise), the event's institution to be `CERTIFIED` (`ERR_INSTITUTION_NOT_CERTIFIED` otherwise), and the event to have a free seat: admission requires `booked_count` strictly below `capacity`, and a booking attempted when `booked_count` equals `capacity` is rejected with `ERR_EVENT_FULL`. A successful booking records the event on the referral's `booked_event_id`, increments the event's `booked_count` by one, and recomputes the participant's `pipeline_stage`. Unbooking reverses the act — the referral returns from `BOOKED` to `DOCS_COMPLETE` (any other starting status yields `ERR_INVALID_STATE`), `booked_event_id` is cleared, the event's `booked_count` is decremented so the seat is restored, and the pipeline stage is recomputed.

Events end in one of two ways. An officer of the hosting institution may cancel a `SCHEDULED` event; an officer of any other institution is rejected with `ERR_UNAUTHORIZED_ROLE`, and a cancellation attempted on a non-`SCHEDULED` event is rejected with `ERR_INVALID_STATE`. Cancellation moves every referral still `BOOKED` against the event back to `DOCS_COMPLETE`, clears each `booked_event_id`, decrements the event's `booked_count` per released seat, and recomputes each affected participant's pipeline stage; the event lands in `CANCELLED`. Alternatively, when the ops epoch finds a `SCHEDULED` event whose `ends_at` the logical clock has passed, the event moves to `COMPLETED` and the same per-referral release runs for any remaining `BOOKED` referrals. An event's roster — the referrals whose `booked_event_id` names the event — is retrievable by coalition staff, the hosting officer, and navigators. Events are listable with optional filters on `institution_id` and `status`.

### 3.6. Account Applications, Decisions, and the Barrier Negotiation

An `InstitutionOfficer` submits an **AccountApplication** by naming the `participant_id`, the `institution_id` (which must equal the officer's own institution identity, else `ERR_UNAUTHORIZED_ROLE`), and the `id_type_presented`. Two optional linkages exist: a `referral_id` and an `event_id`. The `referral_id` is required when no `event_id` is present and optional for an event-day walk-in where `event_id` is present; when both are present, the `event_id` must equal the referral's `booked_event_id`. The referral, when supplied, must belong to the named participant and must be in `DOCS_COMPLETE` or `BOOKED`; any violation of these linkage rules is rejected with `ERR_REFERRAL_MISMATCH`. The participant's documentation must be complete — `ERR_DOCS_INCOMPLETE` when `docs_complete` is false. The institution must be `CERTIFIED`, else `ERR_INSTITUTION_NOT_CERTIFIED`. The `id_type_presented` is one of `STATE_ID`, `MATRICULA_CONSULAR`, `MUNICIPAL_ID`, or `FOREIGN_PASSPORT`; it must appear among the participant's `VERIFIED` documents, and when it is not `STATE_ID` it must additionally be permitted by the certified standard's `accepted_alt_id_types` — failures on either leg surface `ERR_ALT_ID_NOT_ACCEPTED`. A created application lands in `SUBMITTED`. When the application references a referral, that referral moves to `APPLIED`; if the referral was `BOOKED`, its event seat is released — the event's `booked_count` is decremented because the booking is consumed by the application. The participant's `pipeline_stage` is recomputed.

Deciding an application is the officer's approval or decline, expressed by an `outcome` in the payload, with an optional `decline_reason` and an optional `chex_flagged` boolean. The decision endpoint accepts applications in `SUBMITTED` or `REINSTATED`; deciding from any other status is rejected with `ERR_INVALID_STATE`.

Approval moves the application to `OPENED`. Approval requires the institution to still be `CERTIFIED` (`ERR_INSTITUTION_NOT_CERTIFIED` otherwise). When the participant's `prior_banking_record` is `FLAGGED`, or the decision payload's `chex_flagged` is true, approval additionally requires a `RESOLVED` barrier case to exist for this application — approving without one is rejected with `ERR_BARRIER_UNRESOLVED`. When the institution's certified standard declares `requires_financial_education`, approval requires the participant to hold an education pairing in `COMPLETED`, `FOLLOW_UP_DUE`, or `FOLLOW_UP_DONE` status, else `ERR_EDUCATION_REQUIRED`. On approval the server mints the `account_number`, stamps `opened_at` with the current logical-clock reading, records the deciding officer's institution identity as `decided_by_user_id`, and creates two `RetentionCheckpoint` rows for the application, both `PENDING`: an `M6` checkpoint whose `due_date` is the date of `opened_at` plus 183 days, and an `M12` checkpoint whose `due_date` is the date of `opened_at` plus 365 days; each checkpoint's `window_end` is its `due_date` plus 30 days. The linked referral, if any, moves from `APPLIED` to `CLOSED_CONVERTED`; when that referral carries a `campaign_id`, the campaign's `spent_cents` increases by the campaign's `per_conversion_cents`. The participant's `pipeline_stage` is recomputed, and the institution's `accounts_opened_total` is incremented by one.

Decline takes three shapes. A decline with `decline_reason` of `CHEX` moves the application to `DECLINED_CHEX` and creates a **BarrierCase** linked to the application — the ChexSystems second-look — with the case's `participant_id` and `institution_id` copied from the application, its status `OPEN`, its `negotiation_rounds` zero, and `proposed_settlement_cents` and `final_settlement_cents` null. A decline with `decline_reason` of `INSUFFICIENT_ID` moves the application to `DECLINED_ID`, pushes the linked referral to `CLOSED_LOST`, and recomputes the pipeline stage. A decline with `decline_reason` of `OTHER` moves the application to `DECLINED_FINAL` with the same referral closure and pipeline recomputation. On every decline the decision payload's `decline_reason` is recorded as the application's `decline_reason`.

A **BarrierCase** is a three-party negotiation. An officer of the case's institution proposes a remediation settlement by supplying `proposed_settlement_cents` and an optional `resolution_note`; proposing is allowed from `OPEN` or `COUNTERED` (otherwise `ERR_INVALID_STATE`), an officer of another institution is rejected with `ERR_UNAUTHORIZED_ROLE`, and the proposal moves the case to `PLAN_PROPOSED` with the new amount overwriting any previous `proposed_settlement_cents`. An `AgencyNavigator` counters a `PLAN_PROPOSED` case, optionally attaching a `resolution_note`; countering moves the case to `COUNTERED` and increments `negotiation_rounds` by one. The participant — and only the participant whose `id` equals the case's `participant_id`, with anyone else rejected as `ERR_UNAUTHORIZED_ROLE` — accepts a `PLAN_PROPOSED` case, optionally attaching a `resolution_note`; acceptance pins `final_settlement_cents` to the `proposed_settlement_cents` current at accept time, moves the case to `RESOLVED`, cascades the linked application from `DECLINED_CHEX` to `REINSTATED` (leaving its `decided_by_user_id` unchanged until the next decision), and recomputes the participant's pipeline stage. A reinstated application may be decided again; a fresh CHEX decline on it opens a new barrier case. Escalation is the officer's terminal denial: allowed only from `COUNTERED` (otherwise `ERR_INVALID_STATE`) and only once `negotiation_rounds` has reached at least 3 — escalating with rounds remaining is rejected with `ERR_NEGOTIATION_ROUNDS_REMAINING`. Escalation moves the case to `DENIED_FINAL`, cascades the linked application from `DECLINED_CHEX` to `DECLINED_FINAL`, pushes the linked referral to `CLOSED_LOST`, and recomputes the pipeline stage. Barrier cases are listable with optional filters on `application_id`, `participant_id`, `institution_id`, and `status`.

An officer of the owning institution may also report that an opened account closed early, supplying a `closed_at` timestamp. The application must be `OPENED` (`ERR_INVALID_STATE` otherwise), the acting institution must equal the application's `institution_id` (`ERR_UNAUTHORIZED_ROLE` otherwise), and `closed_at` must not be earlier than `opened_at` (`ERR_VALIDATION` otherwise). The transition lands the application in `CLOSED_EARLY` with `closed_at` recorded. Pending retention checkpoints are not resolved at closure time; they remain `PENDING` until the ops epoch evaluates them.

Applications are listable with optional filters on `participant_id`, `institution_id`, `referral_id`, `event_id`, and `status`.

### 3.7. Retention Checkpoints and Epoch Evaluation

Each `RetentionCheckpoint` pairs an `application_id` with a `kind` of `M6` or `M12` and starts `PENDING` with `evaluated_at` null. The ops epoch resolves checkpoints against the logical clock. A `PENDING` checkpoint whose `due_date` has been reached resolves to `EVALUATED_RETAINED` when the application is still `OPENED`. It resolves to `EVALUATED_NOT_RETAINED` when the application is `CLOSED_EARLY` with a `closed_at` date on or before the `due_date`. When the logical clock's date has reached the checkpoint's `window_end` while the application remains `OPENED` but the institution is no longer `CERTIFIED` — so retention cannot be positively confirmed — the checkpoint resolves to `EXPIRED_UNCONFIRMED`. Every resolution stamps `evaluated_at` with the current logical-clock reading. Checkpoints are listable with optional filters on `application_id`, `kind`, and `status`, and are visible to coalition staff and institution officers.

### 3.8. Financial Education Pairings and Follow-Up

A `CoalitionAdmin` or a `FinancialCoach` pairs a participant with a coach by supplying the `participant_id`, the `coach_id`, and a `course_code` of `FOUNDATIONS`, `CREDIT_BASICS`, or `SAVINGS`. When the actor is a `FinancialCoach`, the supplied `coach_id` must equal the acting coach's `X-User-ID`. A coach may hold at most three `ACTIVE` pairings: creation requires the coach's count of `ACTIVE` pairings to be strictly below three, and a create at the limit is rejected with `ERR_COACH_CASELOAD_FULL`. A new pairing lands in `ACTIVE` with `completed_at`, `follow_up_due_at`, and `follow_up_logged_at` all null.

Completion is the coach's act, restricted to the coach whose identifier matches the pairing's `coach_id` — any other coach is rejected with `ERR_UNAUTHORIZED_ROLE` — and allowed only from `ACTIVE` (otherwise `ERR_INVALID_STATE`). Completion stamps `completed_at` with the current logical-clock reading and computes `follow_up_due_at` as `completed_at` plus 30 days. From there the ops epoch moves the pairing from `COMPLETED` to `FOLLOW_UP_DUE` once the logical clock reaches `follow_up_due_at`. Logging the follow-up — again restricted to the pairing's own coach — is allowed only from `FOLLOW_UP_DUE`: attempting it while the pairing is `COMPLETED` but not yet due is rejected with `ERR_FOLLOW_UP_NOT_DUE`, and attempting it from any other status is rejected with `ERR_INVALID_STATE`. A successful log stamps `follow_up_logged_at` and lands the pairing in `FOLLOW_UP_DONE`. Pairings are listable with optional filters on `participant_id`, `coach_id`, and `status`.

### 3.9. Funding Grants, Partner Reports, and the Claim Computation

A `CoalitionAdmin` creates a **FundingGrant** with the `funder_name`, the `program_year`, the `total_cents` of grant funds, and the `per_report_cap_cents` bounding any single report's claim. A new grant is `DRAFT` with `reserved_cents` and `disbursed_cents` zero. Activation moves the grant from `DRAFT` to `ACTIVE`; the same activate capability also returns a `SUSPENDED` grant to `ACTIVE`, and invoking it from any other status is rejected with `ERR_INVALID_STATE`. Both activation and suspension increment the grant's `version`.

Suspending an `ACTIVE` grant (from any other status, `ERR_INVALID_STATE`) runs a cascade: every `PartnerReport` of the grant in `SUBMITTED` moves back to `DRAFT`, and each such report's reservation is released — the grant's `reserved_cents` decreases by the report's `claim_total_cents` and its `available_cents` increases by the same amount. Closing a grant requires it to be `ACTIVE` (`ERR_INVALID_STATE` otherwise) and to carry no pending claims: no report of the grant may be `SUBMITTED` and `reserved_cents` must be zero, with any pending residue rejected as `ERR_GRANT_HAS_PENDING_CLAIMS`. A closed grant is terminal.

An `InstitutionOfficer` drafts a **PartnerReport** by naming the `institution_id` (which must equal the officer's own institution identity), the `grant_id`, the `period_start` and `period_end` ISO dates bounding the reporting period inclusively, an `evaluation_mode` of `PROVISIONAL` or `FINAL`, and the OCC field `expected_grant_version` per §2.6. A `period_start` after `period_end` is rejected with `ERR_VALIDATION`. On creation the report's claim fields are computed as a snapshot, and the grant's `version` is advanced as a ledger-anchor touch.

The claim computation evaluates in a pinned order. First, the eligible-opened set is assembled: the institution's applications in `OPENED` or `CLOSED_EARLY` status whose `opened_at` date falls within the closed period from `period_start` through `period_end`, ordered by ascending `opened_at` with ties broken by ascending `created_at` — never by `id`. The size of this set is the report's `opened_count`. Second, each account is assigned an opening tier by its 1-based rank in that ordering: ranks 1 through 25 earn a gross of 5000 cents, ranks 26 through 100 earn 7500 cents, and ranks beyond 100 earn 10000 cents. Third, each account's net is computed individually as its gross reduced by an administrative withholding of 75 basis points — that is, gross multiplied by 0.9925 — with the per-account net rounded half-up to integer cents before any summation; `opening_claim_cents` is the sum of those per-account nets. Summing gross first and rounding once is forbidden, because the orders disagree on cents: three accounts at gross 5000 yield 14889 by the pinned order (three times 4963) but 14888 by the forbidden order. Fourth, the two retention rates are computed. For each kind, the eligible set is the retention checkpoints of the report's institution, of that kind, whose `due_date` is on or before `period_end`. Under `PROVISIONAL` mode the retained numerator counts checkpoints in `EVALUATED_RETAINED`, `PENDING`, or `EXPIRED_UNCONFIRMED` — an optimistic reading; under `FINAL` mode the retained numerator counts only `EVALUATED_RETAINED` checkpoints, so the same underlying data yields a lower rate. Each rate — `retention_rate_m6` and `retention_rate_m12` — is the retained count divided by the eligible count, rounded half-up to four decimal places; when a kind's eligible set is empty the rate is null, not zero, and contributes nothing to the bonus. Fifth, the `retention_bonus_cents` is a tiered per-retained-account bonus: the retained count is the size of the union of the retained numerator sets across the `M6` and `M12` kinds, and the tier is selected by `retention_rate_m6` as the primary rate — a rate of at least 0.80 earns 2500 cents per retained account, a rate of at least 0.60 but below 0.80 earns 1500 cents per retained account, and anything lower (or a null primary rate) earns nothing; the bonus is the tier rate multiplied by the retained count. Sixth, the `education_stipend_cents` applies only when the institution's certified standard declares `requires_financial_education` and the fraction of eligible-opened accounts whose participant holds a `COMPLETED`, `FOLLOW_UP_DUE`, or `FOLLOW_UP_DONE` pairing is at least 0.5 of `opened_count`; the stipend is then ten percent of the pre-stipend subtotal — `opening_claim_cents` plus `retention_bonus_cents` — rounded half-up to integer cents, and it is computed on that pre-stipend subtotal so it never feeds back into its own base. When the education condition is not met, or `opened_count` is zero, the stipend is zero. Seventh, `claim_total_cents` is the sum of `opening_claim_cents`, `retention_bonus_cents`, and `education_stipend_cents`.

Submission moves a report from `DRAFT` or `REJECTED` to `SUBMITTED` (any other starting status yields `ERR_INVALID_STATE`). The grant must be `ACTIVE` (`ERR_GRANT_NOT_ACTIVE` otherwise). The `claim_total_cents` must not exceed the grant's `per_report_cap_cents` (`ERR_CLAIM_EXCEEDS_CAP`) and must not exceed the grant's `available_cents` (`ERR_INSUFFICIENT_GRANT_FUNDS`). On submission the grant's `reserved_cents` increases by the claim and its `available_cents` decreases by the same amount. A resubmission from `REJECTED` recomputes every claim field against current data before applying the same reservation.

Review is the coalition's act, expressed by an `outcome` in the payload, and is allowed only on a `SUBMITTED` report (`ERR_INVALID_STATE` otherwise). An approving review moves the report to `APPROVED` and converts the reservation to a disbursement: the grant's `reserved_cents` decreases by the claim and its `disbursed_cents` increases by the claim, leaving `available_cents` unchanged. A rejecting review moves the report to `REJECTED` and releases the reservation as compensation: `reserved_cents` decreases by the claim and `available_cents` increases by the claim. Reports are listable with optional filters on `institution_id`, `grant_id`, and `status`.

### 3.10. Outreach Campaigns

A `CoalitionAdmin` launches an **OutreachCampaign** with a `name`, a `zip_cluster` scope key, a `window_start` and `window_end` pair of ISO dates bounding the campaign as a half-open window that includes `window_start` and excludes `window_end`, a `budget_cents`, and the `per_conversion_cents` credited as spend each time one of the campaign's referrals reaches `CLOSED_CONVERTED`. The `window_start` must not fall after the `window_end`. A campaign is `ACTIVE` from creation with `spent_cents` zero; `spent_cents` is the product of `per_conversion_cents` and the count of the campaign's referrals in `CLOSED_CONVERTED`.

Two constraints guard launch. Within a `zip_cluster`, a new campaign conflicts with any existing `ACTIVE` campaign whose window overlaps it — overlap exists when the new `window_start` falls before the existing `window_end` and the existing `window_start` falls before the new `window_end`, with adjacency (a `window_start` exactly equal to another's `window_end`) not counting as overlap — and such a conflict is rejected with `ERR_CAMPAIGN_OVERLAP`. The cluster also carries an aggregate budget cap: the sum of `budget_cents` over the cluster's `ACTIVE` campaigns plus the new campaign's budget must not exceed 500000 cents, with equality allowed, and an overage is rejected with `ERR_CAMPAIGN_BUDGET_EXCEEDED`. Closing a campaign requires it to be `ACTIVE` (`ERR_INVALID_STATE` otherwise) and lands it in `CLOSED`; from that point, no new referral may reference it.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, including state transitions and computed-field refreshes, return `200 OK`. Readers reconstruct each endpoint's request payload, response payload, and side effects from the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/account-standards` | Create an AccountStandard in DRAFT | CoalitionAdmin |
| GET | `/api/account-standards/{id}` | Get one AccountStandard | CoalitionAdmin, InstitutionOfficer, AgencyNavigator, FinancialCoach, Participant |
| POST | `/api/account-standards/{id}/activate` | Activate a standard; supersedes any currently EFFECTIVE standard | CoalitionAdmin |
| POST | `/api/partner-institutions` | Register a partner institution | CoalitionAdmin |
| GET | `/api/partner-institutions` | List institutions with optional filters | CoalitionAdmin, InstitutionOfficer, AgencyNavigator, FinancialCoach, Participant |
| GET | `/api/partner-institutions/{id}` | Get one institution | CoalitionAdmin, InstitutionOfficer, AgencyNavigator, FinancialCoach, Participant |
| POST | `/api/partner-institutions/{id}/suspend` | Suspend a CERTIFIED institution | CoalitionAdmin |
| POST | `/api/partner-institutions/{id}/reinstate` | Reinstate a SUSPENDED institution before certification expiry | CoalitionAdmin |
| POST | `/api/certification-reviews` | Open a review (OCC on institution version); supersedes the live review | CoalitionAdmin |
| GET | `/api/certification-reviews` | List reviews with optional filters | CoalitionAdmin, InstitutionOfficer |
| GET | `/api/certification-reviews/{id}` | Get one review | CoalitionAdmin, InstitutionOfficer |
| POST | `/api/certification-reviews/{id}/score` | Record criteria ratings; computes weighted score | CoalitionAdmin |
| POST | `/api/certification-reviews/{id}/finalize` | Finalize a scored review; applies the institution outcome | CoalitionAdmin |
| POST | `/api/participants` | Register a participant | AgencyNavigator, CoalitionAdmin |
| GET | `/api/participants/{id}` | Get one participant | CoalitionAdmin, AgencyNavigator, InstitutionOfficer, Participant |
| PATCH | `/api/participants/{id}/documents` | Upsert identity documents; recomputes docs completeness and pipeline stage | AgencyNavigator, CoalitionAdmin |
| POST | `/api/referrals` | Create a referral (navigator intake or campaign intake) | AgencyNavigator, CoalitionAdmin |
| GET | `/api/referrals` | List referrals with optional filters | CoalitionAdmin, AgencyNavigator, InstitutionOfficer |
| GET | `/api/referrals/{id}` | Get one referral | CoalitionAdmin, AgencyNavigator, InstitutionOfficer |
| POST | `/api/referrals/{id}/docs-complete` | Mark a referral's documentation complete | AgencyNavigator |
| POST | `/api/referrals/{id}/book` | Book a referral into a scheduled event | AgencyNavigator |
| POST | `/api/referrals/{id}/unbook` | Release a booking and restore the seat | AgencyNavigator |
| POST | `/api/account-opening-events` | Schedule an account-opening event | InstitutionOfficer |
| GET | `/api/account-opening-events` | List events with optional filters | CoalitionAdmin, InstitutionOfficer, AgencyNavigator, Participant |
| GET | `/api/account-opening-events/{id}` | Get one event | CoalitionAdmin, InstitutionOfficer, AgencyNavigator, Participant |
| GET | `/api/account-opening-events/{id}/referrals` | Event roster of booked referrals | CoalitionAdmin, InstitutionOfficer, AgencyNavigator |
| POST | `/api/account-opening-events/{id}/cancel` | Cancel a scheduled event; unbooks all booked referrals | InstitutionOfficer |
| POST | `/api/account-applications` | Submit an account application | InstitutionOfficer |
| GET | `/api/account-applications` | List applications with optional filters | CoalitionAdmin, InstitutionOfficer, AgencyNavigator |
| GET | `/api/account-applications/{id}` | Get one application | CoalitionAdmin, InstitutionOfficer, AgencyNavigator |
| POST | `/api/account-applications/{id}/decision` | Approve or decline an application | InstitutionOfficer |
| POST | `/api/account-applications/{id}/report-closure` | Report early closure of an opened account | InstitutionOfficer |
| GET | `/api/barrier-cases` | List barrier cases with optional filters | CoalitionAdmin, InstitutionOfficer, AgencyNavigator |
| GET | `/api/barrier-cases/{id}` | Get one barrier case | CoalitionAdmin, InstitutionOfficer, AgencyNavigator, Participant |
| POST | `/api/barrier-cases/{id}/propose` | Officer proposes a remediation settlement | InstitutionOfficer |
| POST | `/api/barrier-cases/{id}/counter` | Navigator counters the proposal | AgencyNavigator |
| POST | `/api/barrier-cases/{id}/accept` | Participant accepts the plan; reinstates the application | Participant |
| POST | `/api/barrier-cases/{id}/escalate` | Officer denies after negotiation rounds are exhausted | InstitutionOfficer |
| POST | `/api/education-pairings` | Pair a participant with a financial coach | CoalitionAdmin, FinancialCoach |
| GET | `/api/education-pairings` | List pairings with optional filters | CoalitionAdmin, FinancialCoach, AgencyNavigator |
| GET | `/api/education-pairings/{id}` | Get one pairing | CoalitionAdmin, FinancialCoach, AgencyNavigator |
| POST | `/api/education-pairings/{id}/complete` | Complete a pairing; schedules the follow-up | FinancialCoach |
| POST | `/api/education-pairings/{id}/log-follow-up` | Log a due follow-up | FinancialCoach |
| GET | `/api/retention-checkpoints` | List checkpoints with optional filters | CoalitionAdmin, InstitutionOfficer |
| GET | `/api/retention-checkpoints/{id}` | Get one checkpoint | CoalitionAdmin, InstitutionOfficer |
| POST | `/api/ops/evaluate-due` | Ops epoch: evaluate due checkpoints, lapse certifications, complete events, move due follow-ups | CoalitionAdmin |
| POST | `/api/funding-grants` | Create a grant in DRAFT | CoalitionAdmin |
| GET | `/api/funding-grants/{id}` | Get one grant | CoalitionAdmin, InstitutionOfficer |
| POST | `/api/funding-grants/{id}/activate` | Activate a DRAFT or SUSPENDED grant | CoalitionAdmin |
| POST | `/api/funding-grants/{id}/suspend` | Suspend an ACTIVE grant; releases SUBMITTED reservations | CoalitionAdmin |
| POST | `/api/funding-grants/{id}/close` | Close an ACTIVE grant with no pending claims | CoalitionAdmin |
| POST | `/api/partner-reports` | Create a report in DRAFT with computed claim snapshot (OCC on grant version) | InstitutionOfficer |
| GET | `/api/partner-reports` | List reports with optional filters | CoalitionAdmin, InstitutionOfficer |
| GET | `/api/partner-reports/{id}` | Get one report | CoalitionAdmin, InstitutionOfficer |
| POST | `/api/partner-reports/{id}/submit` | Submit a draft or rejected report; reserves the claim on the grant | InstitutionOfficer |
| POST | `/api/partner-reports/{id}/review` | Coalition approves or rejects a submitted report | CoalitionAdmin |
| POST | `/api/outreach-campaigns` | Launch an outreach campaign | CoalitionAdmin |
| GET | `/api/outreach-campaigns/{id}` | Get one campaign | CoalitionAdmin, AgencyNavigator |
| POST | `/api/outreach-campaigns/{id}/close` | Close an active campaign | CoalitionAdmin |
| POST | `/api/_clock/set_current_utc` | Advance the server logical clock (monotonic) | CoalitionAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SOD_VIOLATION` | 409 |
| `ERR_DOCS_INCOMPLETE` | 422 |
| `ERR_ALT_ID_NOT_ACCEPTED` | 422 |
| `ERR_BARRIER_UNRESOLVED` | 409 |
| `ERR_EDUCATION_REQUIRED` | 409 |
| `ERR_FOLLOW_UP_NOT_DUE` | 409 |
| `ERR_EVENT_WINDOW_CONFLICT` | 409 |
| `ERR_REVIEW_GAP_VIOLATION` | 409 |
| `ERR_CAMPAIGN_OVERLAP` | 409 |
| `ERR_INSTITUTION_NOT_CERTIFIED` | 409 |
| `ERR_STANDARD_NOT_EFFECTIVE` | 409 |
| `ERR_GRANT_NOT_ACTIVE` | 409 |
| `ERR_REFERRAL_MISMATCH` | 409 |
| `ERR_EVENT_NOT_BOOKABLE` | 409 |
| `ERR_EVENT_FULL` | 409 |
| `ERR_COACH_CASELOAD_FULL` | 409 |
| `ERR_INSUFFICIENT_GRANT_FUNDS` | 402 |
| `ERR_CLAIM_EXCEEDS_CAP` | 422 |
| `ERR_CAMPAIGN_BUDGET_EXCEEDED` | 422 |
| `ERR_GRANT_HAS_PENDING_CLAIMS` | 409 |
| `ERR_NEGOTIATION_ROUNDS_REMAINING` | 409 |
| `ERR_CERTIFICATION_LAPSED` | 409 |
