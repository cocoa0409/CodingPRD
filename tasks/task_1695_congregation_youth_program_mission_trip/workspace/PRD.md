# Congregation Youth Mission Trips API — Product Requirements Document

## 1. Introduction

A congregation's youth ministry runs on trust: parents hand over their children for a week of service work hundreds or thousands of miles from home, donors fund the effort, and volunteers step forward as chaperones. Behind that trust sits a machinery of paperwork, money, and compliance that is easy to get wrong in a spreadsheet — parental consent and medical release forms that must be signed, verified, and re-collected when rejected; fundraising ledgers that mix cash, checks, and card gifts with processing fees; scholarship requests scored on household need and awarded from a finite fund; background-screened chaperones whose clearances must remain valid through the last night of the trip; and payment deadlines whose lapses trigger late fees.

This document specifies the Congregation Youth Mission Trips API, mounted under `/youth-ministry`, which governs the full arc of that work for a ministry year. A **Program** anchors the year: it holds the scholarship fund, the award policy, the code of conduct, and the discipline plan. Under it, **Trips** move from `DRAFT` through registration, roster lock, execution, and debrief. Each youth signs up through a **Registration** that lives on two parallel tracks at once — a review/status track and a payment track — and is automatically paired with a **FundraisingAccount** that collects **Donations** and converts their net proceeds into balance credit. **ScholarshipApplications** compete for the program's finite aid fund under strict segregation of duties between the committee that approves and the treasurer who disburses. **Chaperones** advance through background checks, accept or decline trip assignments, and are counted against a strict youth-per-chaperone ratio before a roster may lock.

Time itself is a managed input. The system runs on a logical clock that a `ProgramDirector` advances explicitly; advancing it triggers delinquency sweeps over payment deadlines and expires background checks whose validity has run out. Every mutation is versioned, and the two read-modify-write surfaces most prone to silent overwrite — scholarship policy and trip logistics — are guarded by optimistic concurrency.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their capacity. If either header is missing, or the role value is not one of the declared role names, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the role is valid but not listed among an endpoint's authorized roles, the request is rejected with `ERR_ROLE_FORBIDDEN` (HTTP 403).

The system recognizes exactly six roles: `ProgramDirector`, `TripLeader`, `Treasurer`, `ScholarshipReviewer`, `Guardian`, and `Chaperone`.

- A `ProgramDirector` is the youth ministry director; they own program and trip lifecycle, scholarship policy, participant intake, registration decisions, discipline, screening administration, debrief, and the logical clock.
- A `TripLeader` is an adult trip logistics lead; they own itinerary and lodging and share registration/consent review and chaperone-assignment management.
- A `Treasurer` is the finance officer; they record payments and donations, issue refunds, apply fundraising credit, and disburse approved scholarships — but may never disburse an application they themselves approved.
- A `ScholarshipReviewer` is an aid-committee reviewer who decides and rescinds scholarship applications and never touches money movement.
- A `Guardian` is a parent/guardian self-service operator scoped to their own household's resources.
- A `Chaperone` is a screened adult leader who responds to their own trip assignments and reads their own screening records.

For five of the six roles, `X-User-ID` is an **opaque operator identifier** not tied to any persisted entity: for `ProgramDirector`, `TripLeader`, `Treasurer`, `ScholarshipReviewer`, and `Guardian` the server may record the value (for example, as `reviewed_by_user_id` on a consent form, `approved_by_user_id` or `disbursed_by_user_id` on a scholarship application, or `guardian_user_id` on a participant and registration) but never compares it to any entity's `id`. In particular, a `Guardian`'s ownership anchor is the stored `guardian_user_id` string on participant and registration records — a guardian may act only on resources whose `guardian_user_id` equals the presented `X-User-ID`; acting on another guardian's resource is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). The sixth role is different: when `X-User-Role` is `Chaperone`, `X-User-ID` is the `id` of the acting `Chaperone` entity, and ownership checks on chaperone assignments and chaperone records compare the resource's `chaperone_id` (or the chaperone record's own `id`) against `X-User-ID`, again rejecting mismatches with `ERR_NOT_RESOURCE_OWNER`.

Segregation of duties overlays ownership. A reviewer of a registration or consent form must not be that registration's `guardian_user_id`; a scholarship decide actor must differ from the registration's `guardian_user_id`; and a scholarship disburser must differ from the application's `approved_by_user_id`. Each violation is rejected with `ERR_SOD_VIOLATION` (HTTP 403). Because the approver id is recorded from a `ScholarshipReviewer`'s `X-User-ID`, a user who happens to hold both the reviewer and treasurer capacities is still blocked by the identifier comparison.

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

List endpoints accept two query parameters. `limit` caps the number of returned items: it defaults to 10 when omitted, may not be less than 1, and may not exceed 100. `offset` says how many items to skip and defaults to 0. Every list response is sorted by `created_at` in ascending order unless explicitly stated otherwise, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

The system never reads the wall clock. All temporal evaluation — deadlines, screening validity, trip windows — runs against a logical clock exposed as an admin capability. Before any operator sets it, the clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time. A `ProgramDirector` advances the clock by supplying a `to_iso8601` instant; the response carries no resource payload. Each advance is an ops-run epoch: the system first runs the delinquency sweep over every trip's deposit and final-payment deadlines, then runs the background-check expiry sweep, refreshing every recomputed rollup that those cascades touch. Donation `received_at` and payment `posted_at` timestamps are likewise stamped from this logical clock at creation.

### 2.5. Common Resource Properties and Mutation Semantics

Every entity in this API — Program, Trip, Participant, Registration, ConsentForm, FundraisingAccount, Donation, Payment, ScholarshipApplication, Chaperone, BackgroundCheck, ChaperoneAssignment, ItineraryItem, and LodgingReservation — carries the standard system-managed fields:

- `id`: a server-minted UUID with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at`: an ISO 8601 UTC timestamp refreshed on every mutation.
- `version`: an integer that starts at its initial value on creation and increments by exactly 1 on every mutation of the entity — including mutations caused by system cascades and recomputes, not just direct client edits.

Because any state transition, cascade hop, or derived-field reconciliation on a resource bumps its `version` and refreshes `updated_at`, clients must re-read a resource after any operation that could have touched it before performing a version-guarded write.

### 2.6. Money, Precision, and Rounding

All monetary quantities are integer cents — never floats, never decimal strings. Percentages expressed as basis points (as in the scholarship policy's `max_award_pct_bp`, where 10000 represents 100%) are integers. Wherever a division or percentage produces fractional cents, the rounding method is **round half up**, and each calculation that needs rounding applies it at a pinned step: the donation card fee rounds its percentage component to the nearest cent before adding the flat component; the provisional cost share rounds the lodging division once; the final cost share rounds the per-person lodging division and then distributes the signed remainder one cent at a time rather than summing first and rounding afterward; a late fee rounds its percentage component before being compared against the flat minimum. Need scoring works in integer points, with each component bonus capped individually before the total cap is applied.

### 2.7. Optimistic Concurrency Control

Two write surfaces are guarded by optimistic concurrency, because each is a classic read-modify-write where a stale snapshot would silently overwrite another operator's decision.

A request to replace a program's scholarship policy must carry `expected_program_version` holding the `version` of the Program the client last observed. If the program's current `version` differs — because another operator changed the policy or closed the program in the meantime — the request is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412).

A request to edit a trip's logistics fields must likewise carry `expected_trip_version` matching the trip's current `version`. Any lifecycle transition (opening registration, locking the roster, starting, cancelling) or earlier edit advances that version; an edit presented against an older version is rejected with `ERR_STALE_TRIP_VERSION` (HTTP 412). Both version fields are non-optional on their respective endpoints. No other endpoint takes a version field.

### 2.8. Validation Order

A single request can fail in several ways at once, so the order in which checks run is part of the contract. When a request violates more than one rule, the error reported is the one from the earliest applicable check in this sequence:

1. **Presence and shape of the caller context**: the two headers and a declared role name (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Body well-formedness**: required fields present, enum values within their declared sets (including `decision`, `to_status`, and `sanction` values — otherwise `ERR_INVALID_ENUM`), integer ranges respected (an `amount_cents` of zero or below, a `grade` outside 6 through 12, a `capacity_youth` below 1, and similar violations raise `ERR_INVALID_REQUEST`), and every start-before-end pair ordered (`check_out_date` strictly after `check_in_date`, `end_date` strictly after `start_date`, `end_at` strictly after `start_at` — otherwise `ERR_INVALID_DATE_RANGE`).
3. **Role authorization**: the presented role must appear in the endpoint's authorized list (`ERR_ROLE_FORBIDDEN`).
4. **Existence**: path identifiers are resolved left to right, and body-referenced identifiers (`trip_id`, `participant_id`, `chaperone_id`, `registration_id`) must also exist; the first missing resource produces its specific 404 (`ERR_PROGRAM_NOT_FOUND`, `ERR_TRIP_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_CONSENT_FORM_NOT_FOUND`, `ERR_FUNDRAISING_ACCOUNT_NOT_FOUND`, `ERR_DONATION_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_SCHOLARSHIP_APPLICATION_NOT_FOUND`, `ERR_CHAPERONE_NOT_FOUND`, `ERR_BACKGROUND_CHECK_NOT_FOUND`, `ERR_CHAPERONE_ASSIGNMENT_NOT_FOUND`, or `ERR_LODGING_RESERVATION_NOT_FOUND`).
5. **Ownership and segregation of duties**: guardian ownership, chaperone self-response, reviewer-is-not-guardian, and disburser-is-not-approver (`ERR_NOT_RESOURCE_OWNER`, `ERR_SOD_VIOLATION`).
6. **State preconditions**: the target entity's current status must admit the requested transition or child operation (`ERR_PROGRAM_NOT_OPEN`, `ERR_TRIP_STATE_FORBIDS_ACTION`, `ERR_REGISTRATION_STATE_FORBIDS_ACTION`, `ERR_CONSENT_FORM_STATE_FORBIDS_ACTION`, `ERR_APPLICATION_STATE_FORBIDS_ACTION`, `ERR_CHECK_STATE_FORBIDS_ACTION`, `ERR_ASSIGNMENT_STATE_FORBIDS_ACTION`, `ERR_DONATION_STATE_FORBIDS_ACTION`, `ERR_PAYMENT_STATE_FORBIDS_ACTION`, `ERR_LODGING_STATE_FORBIDS_ACTION`, `ERR_ACCOUNT_CLOSED`). When a single call would fail both a registration-state gate and a fundraising-account status gate, the registration-state error is reported first.
7. **Optimistic concurrency**: the `expected_program_version` / `expected_trip_version` comparison (`ERR_STALE_PROGRAM_VERSION`, `ERR_STALE_TRIP_VERSION`).
8. **Child-protection safety gates**: barred participants, screening validity through trip end, roster-lock ratio, insurance tier (`ERR_PARTICIPANT_BARRED`, `ERR_SCREENING_NOT_VALID_THROUGH_TRIP`, `ERR_CHAPERONE_RATIO_UNMET`, `ERR_INSURANCE_TIER_INSUFFICIENT`).
9. **Required-forms referential checks**: presence and status of the three required consent types, and non-empty medical notes on a medical release (`ERR_REQUIRED_FORMS_INCOMPLETE`).
10. **Temporal windows**: registration windows, itinerary containment, open-registration earliness (`ERR_REGISTRATION_WINDOW_CLOSED`, `ERR_ITINERARY_OUTSIDE_TRIP_WINDOW`).
11. **Uniqueness, overlap, and capacity constraints**: duplicates, room and vehicle overlaps, capacity floors, waitlist ordering, and the structural lock-roster gates (`ERR_DUPLICATE_REGISTRATION`, `ERR_DUPLICATE_CONSENT_FORM_TYPE`, `ERR_DUPLICATE_ACTIVE_APPLICATION`, `ERR_SCREENING_IN_PROGRESS_EXISTS`, `ERR_DUPLICATE_LEAD_CHAPERONE`, `ERR_DUPLICATE_ASSIGNMENT`, `ERR_ROOM_ALREADY_BOOKED`, `ERR_VEHICLE_SCHEDULE_CONFLICT`, `ERR_CHAPERONE_TRIP_OVERLAP`, `ERR_CAPACITY_FLOOR`, `ERR_WAITLIST_NOT_HEAD`, `ERR_NO_WAITLIST_CAPACITY`, `ERR_EMPTY_ROSTER`, `ERR_EMERGENCY_PROTOCOL_MISSING`, `ERR_LODGING_CAPACITY_INSUFFICIENT`).
12. **Money gates, checked last**: deposit coverage at confirm, deposit lapse at roster lock, scholarship fund availability and zero-award, and zero available credit (`ERR_DEPOSIT_NOT_COVERED`, `ERR_UNPAID_BALANCES_REMAIN`, `ERR_SCHOLARSHIP_FUND_EXHAUSTED`, `ERR_AWARD_WOULD_BE_ZERO`, `ERR_NO_CREDIT_AVAILABLE`).

So, for example, a registration review issued by the household's own guardian surfaces `ERR_SOD_VIOLATION` before any consideration of whether the forms are verified; and an approve-decision against an exhausted scholarship fund surfaces `ERR_SCHOLARSHIP_FUND_EXHAUSTED` rather than `ERR_AWARD_WOULD_BE_ZERO`, because fund exhaustion is checked first within the fiscal gate.

### 2.9. Flat Collections, Cross-Aggregate Rollups, and Derived-Field Reconciliation

All collections hang directly off the `/youth-ministry` prefix; there is no nested URL hierarchy to validate beyond the specific sub-paths in §4 (consent forms and payments under a registration, donations under a fundraising account, background checks under a chaperone, itinerary items and lodging reservations under a trip). Identifiers are nonetheless foreign keys across aggregates — a registration names its `trip_id` and `participant_id`, a scholarship application names its `registration_id` — and existence of those referenced resources is enforced per §2.8.

Many fields on Trip, Registration, FundraisingAccount, Program, and Chaperone are **computed rollups** maintained by the server: `seats_taken`, `confirmed_youth_count`, `cleared_chaperone_count`, `required_cleared_chaperones`, `ratio_compliant`, and `lodging_cost_total_cents` on the trip; `provisional_cost_share_cents`, `final_cost_share_cents`, `late_fees_total_cents`, `covered_cents`, and `amount_due_cents` on the registration; the program's scholarship fund triple; and the chaperone's `current_screening_expires_at`. Clients never write these. Every operation that changes an input to one of these rollups recomputes the rollup synchronously within the same request, and each recomputation is a mutation of the owning entity as described in §2.5.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Ministry Year: Programs and Their Policy

A `ProgramDirector` opens a ministry year by creating a program with a `name`, a `ministry_year` label such as "2026-2027", the total aid pool `scholarship_fund_total_cents`, and two governance documents: the `code_of_conduct_text` every participant will acknowledge through a conduct-agreement form, and the `discipline_policy_text` that describes the progressive discipline plan applied when a participant is dismissed. Three policy knobs ride along, each optional at creation: `max_award_pct_bp` (the maximum award as basis points of a registration's cost basis, defaulting to 5000 and bounded between 0 and 10000), `per_registration_cap_cents` (an absolute cap on any single award, defaulting to 150000 cents and never negative), and `default_chaperone_ratio` (the maximum number of youth per cleared chaperone, defaulting to 5 and at least 1). A new program starts `OPEN` with its scholarship fund triple initialized: `scholarship_reserved_cents` at 0, `scholarship_disbursed_cents` at 0, and `scholarship_available_cents` equal to the total pool.

The fund triple is a conserved quantity: `scholarship_reserved_cents` is the sum of `award_cents` over all of the program's applications in `APPROVED`, `scholarship_disbursed_cents` is the sum over applications in `DISBURSED`, and `scholarship_available_cents` is always the total pool minus reserved minus disbursed. After every scholarship mutation, the three still sum to `scholarship_fund_total_cents`. Applications "whose registration's trip belongs to the program" are the input set for this rollup.

The policy knobs can be revised while the program lives, through a full replacement of `max_award_pct_bp` and `per_registration_cap_cents` guarded by `expected_program_version` as described in §2.7. Finally, a director closes the year: closing requires the program to be `OPEN` and every one of its trips to have reached `DEBRIEFED` or `CANCELLED`; otherwise the close is rejected with `ERR_PROGRAM_HAS_OPEN_TRIPS` (HTTP 409). A successful close moves the program to `CLOSED`, which is terminal, and increments `version`. Creating trips, participants, or chaperones under a program that is not `OPEN` fails with `ERR_PROGRAM_NOT_OPEN`.

### 3.2. Trip Setup, Logistics, and the Registration Window

Trips are created under a program by a `ProgramDirector` with a `name`, a `destination_name`, and a `destination_type` of `IN_STATE`, `OUT_OF_STATE`, or `INTERNATIONAL`. The destination type determines the `required_insurance_tier` stamped on the trip: `NONE` for in-state, `DOMESTIC` for out-of-state, and `INTERNATIONAL` for international travel. The date window `start_date` / `end_date` (both ISO dates, end strictly after start) frames everything that follows; `capacity_youth` (at least 1) sets the youth seat count; `base_cost_cents` (at least 0) and `deposit_cents` (never negative and never exceeding `base_cost_cents`) define the money milestones; `chaperone_ratio` sets the trip-specific youth-per-chaperone limit and must be at least 1 and no greater than the program's `default_chaperone_ratio` — a trip may be stricter than the program default but never looser.

Four timestamps govern the trip's calendar: `registration_open_at` and `registration_close_at` bound the registration window, while `deposit_due_at` and `final_payment_due_at` are the deadlines the delinquency sweep evaluates. `emergency_protocol_text` documents the emergency protocol; it defaults to empty and may stay empty for an in-state trip, but a trip whose `destination_type` is not `IN_STATE` cannot lock its roster until the text is non-empty. A new trip is `DRAFT` with all rollups zeroed.

While a trip is still early — `DRAFT`, `REGISTRATION_OPEN`, or `REGISTRATION_CLOSED` — the director may revise logistics through a version-guarded edit accepting any of `name`, `capacity_youth`, `chaperone_ratio`, and `emergency_protocol_text` alongside the required `expected_trip_version`. Two rules protect committed state: `capacity_youth` may not drop below the trip's current `seats_taken` (`ERR_CAPACITY_FLOOR`, HTTP 409), and edits are no longer permitted once the trip is `IN_PROGRESS` or later (`ERR_TRIP_STATE_FORBIDS_ACTION`). Because the provisional cost share divides by `capacity_youth`, changing capacity while pre-lock recomputes `provisional_cost_share_cents` for every non-terminal registration of the trip.

#### The trip lifecycle proper

From `DRAFT`, opening registration requires three things, in the order the state machine checks them: the trip must be `DRAFT` (otherwise `ERR_TRIP_STATE_FORBIDS_ACTION`), the parent program must be `OPEN` (`ERR_PROGRAM_NOT_OPEN`), and the logical clock must be at or past `registration_open_at` — attempting to open early is rejected with `ERR_REGISTRATION_WINDOW_CLOSED` (HTTP 422). Success moves the trip to `REGISTRATION_OPEN`.

Closing registration moves `REGISTRATION_OPEN` to `REGISTRATION_CLOSED` with no further gates. Locking the roster — `REGISTRATION_CLOSED` to `ROSTER_LOCKED` — is the trip's big checkpoint and runs a chain of gates: the trip must be in `REGISTRATION_CLOSED` (`ERR_TRIP_STATE_FORBIDS_ACTION`); `ratio_compliant` must be true (`ERR_CHAPERONE_RATIO_UNMET`, HTTP 422 — with zero confirmed youth the requirement is zero and this passes vacuously, though the next gate stops an empty roster); every `CONFIRMED` registration must carry an `insurance_tier` at or above the trip's `required_insurance_tier` on the ordering `NONE` below `DOMESTIC` below `INTERNATIONAL` (`ERR_INSURANCE_TIER_INSUFFICIENT`, HTTP 422); `confirmed_youth_count` must be at least 1 (`ERR_EMPTY_ROSTER`, HTTP 422); the emergency protocol gate above (`ERR_EMERGENCY_PROTOCOL_MISSING`, HTTP 422); the total `room_capacity` over `CONFIRMED` lodging reservations must be at least `confirmed_youth_count` plus `cleared_chaperone_count` (`ERR_LODGING_CAPACITY_INSUFFICIENT`, HTTP 422); and, checked last among the lock gates, every `CONFIRMED` registration must still have `covered_cents` at least `deposit_cents` — a registration whose deposit lapsed through a refund blocks the lock with `ERR_UNPAID_BALANCES_REMAIN` (HTTP 402).

A successful lock does three things. It computes `final_cost_share_cents` for every `CONFIRMED` registration via the waterfall in §3.6. It recomputes each confirmed registration's `payment_status` against the final basis: coverage of the final share plus late fees means `PAID_IN_FULL`; otherwise coverage of at least the deposit means `PARTIALLY_PAID`; otherwise `PENDING_DEPOSIT`. Because the final basis can exceed the provisional one, a registration that showed `PAID_IN_FULL` on the provisional basis can be **downgraded** by the lock. And it increments the trip's `version`.

Starting the trip (`ROSTER_LOCKED` to `IN_PROGRESS`) re-checks two things at start time: `ratio_compliant` is re-evaluated (`ERR_CHAPERONE_RATIO_UNMET`), and the logical clock must have reached the trip's start instant — midnight UTC at the beginning of `start_date` (otherwise `ERR_TRIP_STATE_FORBIDS_ACTION`). Debrief (`IN_PROGRESS` to `DEBRIEFED`) is allowed only once the clock has reached midnight UTC on the day after `end_date`. Debrief records the post-trip report — `debrief_summary`, `debrief_actual_participant_count`, `debrief_incident_count`, and `debrief_lessons_learned` from the payload — stamps `debriefed_at` from the clock (it is empty until then), and cascades: every `CONFIRMED` registration auto-transitions to `COMPLETED`, and every still-`OPEN` fundraising account belonging to those completed registrations closes.

#### Cancelling a trip

Cancellation is always available to a `ProgramDirector` and takes an optional `reason`, but its blast radius depends entirely on the branch. From `DRAFT`, cancel is quiet: no registrations can exist before registration opens, so there is no cascade at all — only the trip's own `version` advances.

From `REGISTRATION_OPEN`, `REGISTRATION_CLOSED`, `ROSTER_LOCKED`, or `IN_PROGRESS`, cancel runs the full depth-3 cascade. Hop 1: every registration in `DRAFT`, `SUBMITTED`, `APPROVED`, `WAITLISTED`, or `CONFIRMED` moves to `CANCELLED`. Hop 2, per cancelled registration: its `OPEN` fundraising account closes; each of its consent forms in `SUBMITTED`, `VERIFIED`, or `REJECTED` is `VOIDED`; its scholarship application moves `UNDER_REVIEW` to `WITHDRAWN`, `APPROVED` to `RESCINDED`, or `DISBURSED` to `RETURNED`; and every `POSTED` payment is auto-refunded to `REFUNDED`, flipping the registration's `payment_status` to `REFUNDED` if at least one payment was refunded. Hop 3: each scholarship status change recomputes the program fund triple — a `RESCINDED` application releases its reserved amount back to available, while a `RETURNED` application releases its disbursed amount. When a locked trip is cancelled, the final cost shares already recorded on the cancelled registrations are left in place.

### 3.3. Participants, Registration Intake, and the Review Pipeline

Participants are the youth. A `Guardian` creating a participant supplies `program_id`, `family_key` (a household grouping key that siblings share — it later drives the scholarship sibling bonus), `first_name`, `last_name`, `birth_date`, `grade` (an integer from 6 to 12), `annual_income_bracket` (one of `BAND_A`, `BAND_B`, `BAND_C`, `BAND_D`, or `UNDISCLOSED`, the self-reported household income band used in need scoring), and `household_size` (persons in the household, at least 1). The new participant's `guardian_user_id` is stamped from the caller's `X-User-ID`; a `ProgramDirector` may create a participant on a family's behalf but must then pass `guardian_user_id` explicitly. A participant's `barred_until` starts empty; it is the discipline system's marker and matters at intake time below.

A registration joins one participant to one trip. Creating one — by the owning `Guardian` or a `ProgramDirector` — takes `trip_id`, `participant_id`, an `insurance_tier` of `NONE`, `DOMESTIC`, or `INTERNATIONAL`, and a `fundraising_goal_cents`. The create is gated by state and safety: the trip must be `REGISTRATION_OPEN` and the clock must not be strictly past `registration_close_at` (`ERR_REGISTRATION_WINDOW_CLOSED`); the participant must not be barred — `barred_until` empty or earlier than the clock (`ERR_PARTICIPANT_BARRED`, HTTP 409); and there must be no other non-terminal registration for the same (trip, participant) pair (`ERR_DUPLICATE_REGISTRATION`, HTTP 409). A successful create produces a registration in `DRAFT` on the status track and `PENDING_DEPOSIT` on the payment track, copies `guardian_user_id` from the participant as the ownership anchor, computes the first `provisional_cost_share_cents`, and auto-opens the registration's one-to-one **FundraisingAccount** with `goal_cents` set from `fundraising_goal_cents`.

Consent paperwork rides on the registration. Three form types are required — `PARENTAL_CONSENT`, `MEDICAL_RELEASE`, and `CONDUCT_AGREEMENT` — while `MEDIA_RELEASE` is optional. Creating a consent form (by the guardian or a director) requires the registration to be in `DRAFT` or `SUBMITTED` (`ERR_REGISTRATION_STATE_FORBIDS_ACTION`), and only one form per `form_type` may exist in `SUBMITTED` or `VERIFIED` (`ERR_DUPLICATE_CONSENT_FORM_TYPE`, HTTP 409). The payload carries `form_type`, `signed_by_name`, and `signed_at`; `medical_notes` defaults to empty but a `MEDICAL_RELEASE` with empty notes is rejected with `ERR_REQUIRED_FORMS_INCOMPLETE` (HTTP 422). A new form is `SUBMITTED`.

Review of a form is done by a `ProgramDirector` or `TripLeader` who must not be the registration's guardian (`ERR_SOD_VIOLATION`). Reviewing with `decision` of `VERIFY` requires the form to be `SUBMITTED` and the registration to be in `DRAFT` or `SUBMITTED`; it moves the form to `VERIFIED`, stamps `reviewed_by_user_id` from the caller, and — when the form is a `CONDUCT_AGREEMENT` — flips the registration's `conduct_acknowledged` to true. Reviewing with `decision` of `REJECT` under the same preconditions moves the form to `REJECTED` and records `reviewed_by_user_id` and a `rejection_reason`. The cycle is unbounded: a guardian (or director) may resubmit a `REJECTED` form while the registration is still in `DRAFT` or `SUBMITTED`, replacing `signed_by_name`, `signed_at`, and `medical_notes` from the payload, clearing `rejection_reason`, and returning the form to `SUBMITTED`. An unknown `decision` value is an `ERR_INVALID_ENUM` (HTTP 400); a review attempted against a form not `SUBMITTED`, or a resubmit of a form not `REJECTED`, is an `ERR_CONSENT_FORM_STATE_FORBIDS_ACTION` (HTTP 409).

Submission of the registration itself — `DRAFT` to `SUBMITTED`, by the guardian or a director — requires the trip to be `REGISTRATION_OPEN` and all three required form types to exist with status `SUBMITTED` or `VERIFIED`; missing or still-rejected paperwork surfaces `ERR_REQUIRED_FORMS_INCOMPLETE`.

The review decision on a `SUBMITTED` registration belongs to a `ProgramDirector` or `TripLeader` who, again, must not be the registration's `guardian_user_id`. With `decision` of `APPROVE`, the checks run in priority order: registration `SUBMITTED`, trip still `REGISTRATION_OPEN`, the segregation-of-duties check, all three required forms `VERIFIED` (a merely-submitted form is not enough here), and the participant not barred — before the capacity fork. If `seats_taken` is below `capacity_youth`, the registration becomes `APPROVED` and `seats_taken` is recomputed; if the trip is full, the same approval forks the registration to `WAITLISTED` — a successful outcome, not an error. With `decision` of `REJECT` (optionally carrying a `reason`), the registration becomes `REJECTED` — terminal — and the system closes its `OPEN` fundraising account and voids every consent form in `SUBMITTED`, `VERIFIED`, or `REJECTED`.

Waitlisted registrations are ordered: the head of a trip's waitlist is the `WAITLISTED` registration with the earliest `created_at`, ties broken by the participant's `created_at` ascending; a registration `id` is never a tie-break input. Promotion from `WAITLISTED` to `APPROVED`, by a director or trip leader, requires the trip to be `REGISTRATION_OPEN`, at least one free seat (`seats_taken` below `capacity_youth`, else `ERR_NO_WAITLIST_CAPACITY`, HTTP 409), and the target to be the head of that order (else `ERR_WAITLIST_NOT_HEAD`, HTTP 409).

Confirmation — `APPROVED` to `CONFIRMED`, by a `ProgramDirector` — is the family's financial commitment point: it requires the trip to be `REGISTRATION_OPEN` or `REGISTRATION_CLOSED`, and `covered_cents` to be at least the trip's `deposit_cents`, with exact equality passing (`ERR_DEPOSIT_NOT_COVERED`, HTTP 402 otherwise). Confirming recomputes the trip's `seats_taken` and `confirmed_youth_count` and re-evaluates `ratio_compliant`.

### 3.4. Money In: Payments, Donations, and Fundraising Credit

A registration's money position lives in a handful of computed fields. `covered_cents` is the sum of `amount_cents` over the registration's `POSTED` payments, plus `fundraising_credit_applied_cents`, plus `scholarship_awarded_cents`. `amount_due_cents` is the cost basis in force — provisional before roster lock, final after — plus `late_fees_total_cents`, minus `covered_cents`, floored at zero. The payment dimension's baseline status is derived continuously: covering the full amount due (when that total is greater than zero) yields `PAID_IN_FULL`; otherwise covering at least `deposit_cents` yields `PARTIALLY_PAID`; otherwise `PENDING_DEPOSIT`. `DELINQUENT` overlays the baseline when a sweep fires, and `REFUNDED` is reachable only through the auto-refund of at least one payment on withdraw or trip cancel.

Payments themselves are posted by a `Treasurer` or the owning guardian against a registration in `APPROVED` or `CONFIRMED` (`ERR_REGISTRATION_STATE_FORBIDS_ACTION` otherwise), carrying a positive `amount_cents` and a `method` of `CASH`, `CHECK`, or `CARD_ONLINE`. The new payment is `POSTED` with `posted_at` stamped from the logical clock, and the registration's coverage and payment status are recomputed immediately — a payment can cure a `DELINQUENT` registration, per the cure rules in §3.6. A treasurer may refund a `POSTED` payment (optionally with a `reason`); refunding a payment that is not `POSTED` is rejected with `ERR_PAYMENT_STATE_FORBIDS_ACTION`. A refund recomputes coverage and can downgrade the payment status — from `PARTIALLY_PAID` back to `PENDING_DEPOSIT` when coverage drops below the deposit, or from `PAID_IN_FULL` to `PARTIALLY_PAID`.

The fundraising side is deliberately independent of approval: donations may be recorded while the registration is still a draft, because the only state gate on the donation create is that the account be `OPEN` (`ERR_ACCOUNT_CLOSED` otherwise). A `Treasurer` records a donation against the account named in the path — the donation's `fundraising_account_id` is taken from that path — with `donor_name`, a positive `amount_cents`, and a `channel` of `CASH`, `CHECK`, or `CARD_ONLINE`. The channel determines `fee_cents` at creation: cash carries no fee; a check carries a flat 25 cents; an online card gift carries its 2.9% percentage component rounded half up to the nearest cent first, then plus a flat 30 cents. The donation is `RECEIVED` with `received_at` stamped from the clock.

The account maintains four rollups over its donations in `RECEIVED` or `APPLIED` — refunded donations drop out of every sum: `raised_gross_cents` (total of `amount_cents`), `fee_total_cents` (total of `fee_cents`), `raised_net_cents` (gross minus fees), and `available_credit_cents` (net minus the `credit_applied_cents` already moved). `goal_met` is a gross-basis comparison — true when `goal_cents` is positive and `raised_gross_cents` is at least `goal_cents`, with exact equality counting. This dual basis is deliberate: donor-facing progress and the scholarship fundraising bonus use the gross figure, while only fee-free net value may move onto the trip balance, so identical donation data yields less credit than progress.

Applying credit, a `Treasurer` action, requires the account `OPEN` (`ERR_ACCOUNT_CLOSED`), the registration in `APPROVED` or `CONFIRMED` (`ERR_REGISTRATION_STATE_FORBIDS_ACTION` — and when both a registration-state gate and the account gate would fail, the registration-state error is reported first), and `available_credit_cents` greater than zero (`ERR_NO_CREDIT_AVAILABLE`, HTTP 422). The operation moves the **full** available net credit: `credit_applied_cents` becomes `raised_net_cents`, the registration's `fundraising_credit_applied_cents` grows by the delta, coverage and payment status are recomputed, and every `RECEIVED` donation is swept to `APPLIED`. A donation in `APPLIED` can never be refunded; refunding a donation requires it to still be `RECEIVED` (`ERR_DONATION_STATE_FORBIDS_ACTION` otherwise), and a successful refund removes it from all four account sums. When the registration finally reaches any terminal status — rejected, withdrawn, dismissed, cancelled, or completed — its account closes; `RECEIVED` donations in a closed account stay refundable, while credits already applied are unaffected.

### 3.5. Scholarships: Need Scoring, Award, and Segregated Disbursement

A family applies for aid on a registration in `APPROVED` or `CONFIRMED` (guardian or director; `ERR_REGISTRATION_STATE_FORBIDS_ACTION` otherwise), supplying `registration_id` and a positive `requested_cents`. One active application per registration: a second application while one exists in `UNDER_REVIEW` or `APPROVED` is rejected with `ERR_DUPLICATE_ACTIVE_APPLICATION` (HTTP 409). The new application is `UNDER_REVIEW` with `award_cents` at 0 and a fresh `need_score`.

The need score is a weighted sum, recomputed from current data both at creation and again inside every decide call — never stored stale. The income band contributes a base: `BAND_A` 50 points, `BAND_B` 35, `BAND_C` 20, `BAND_D` 5, `UNDISCLOSED` 0. Household size adds 5 points per person beyond two, capped at 20. Siblings on the same trip add 10 points each, capped at 20 — counted as other registrations on the same trip whose participant shares this participant's `family_key` and whose registration status is `APPROVED` or `CONFIRMED`. Fundraising adds 10 points if the account's `goal_cents` is positive and `raised_gross_cents` has reached it, else 5 points if any gross amount has been raised, else 0. The total is capped at 100, with each bonus capped before the total cap.

Deciding belongs to a `ScholarshipReviewer`. With `decision` of `DENY` (optionally with a `reason`), the application moves to `DENIED` and `decision_reason` is recorded; the family or a director may appeal, returning it to `UNDER_REVIEW` with `decision_reason` cleared — an unbounded cycle, requiring the registration to still be `APPROVED` or `CONFIRMED`. With `decision` of `APPROVE`, a chain of gates applies: the application must be `UNDER_REVIEW` (`ERR_APPLICATION_STATE_FORBIDS_ACTION`); the registration must be `APPROVED` or `CONFIRMED`; the reviewer must differ from the registration's `guardian_user_id` (`ERR_SOD_VIOLATION`); the program's `scholarship_available_cents` must be positive (`ERR_SCHOLARSHIP_FUND_EXHAUSTED`, HTTP 402); and the computed award must be positive (`ERR_AWARD_WOULD_BE_ZERO`, HTTP 422) — fund exhaustion is evaluated before the zero-award check.

The award computation has a pinned evaluation order that breaks the apparent circle between award and balance. First, `need_score` is recomputed from current data. Second, the cost basis is chosen: the registration's `provisional_cost_share_cents` while the trip is in `DRAFT`, `REGISTRATION_OPEN`, or `REGISTRATION_CLOSED`, and its `final_cost_share_cents` once the trip is `ROSTER_LOCKED` or later — the basis never includes late fees, prior fundraising credit, or any scholarship, this registration's or others'. Third, the need cap is the cost basis multiplied by `need_score` hundredths and by `max_award_pct_bp` ten-thousandths, rounded half up to the nearest cent. Fourth, `award_cents` is the minimum of four values: `requested_cents`, the need cap, the program's `per_registration_cap_cents`, and the program's `scholarship_available_cents`. On approval, `need_score` and `award_cents` are stored, `scholarship_reserved_cents` rises by the award (and available falls correspondingly), and `approved_by_user_id` is stamped from the caller.

Disbursement belongs to a `Treasurer` and is segregated: the disbursing user's `X-User-ID` must differ from `approved_by_user_id` (`ERR_SOD_VIOLATION`), the application must be `APPROVED`, and the registration must still be `APPROVED` or `CONFIRMED`. Disbursing shifts the fund triple — reserved falls by the award, disbursed rises by it, available unchanged — sets the registration's `scholarship_awarded_cents` to the award, stamps `disbursed_by_user_id`, and recomputes coverage and payment status.

Three exits exist besides disbursement. A reviewer may rescind an `APPROVED` application (optionally with a `reason`), releasing the reservation back to available. A system cascade on registration withdraw, dismiss, or trip cancel moves an `UNDER_REVIEW` application to `WITHDRAWN`, and a withdraw or trip cancel — but not a dismiss — moves a `DISBURSED` application to `RETURNED`, which releases the disbursed amount back to available, zeroes the registration's `scholarship_awarded_cents`, and recomputes its coverage. On dismissal, a disbursed award is retained: funds already spent are not clawed back.

### 3.6. Cost Shares, Late Fees, and the Delinquency Sweep

The provisional share answers "what should families budget right now?" It equals the trip's `base_cost_cents` plus the trip's `lodging_cost_total_cents` divided by `capacity_youth`, that division rounded half up to the nearest cent. The denominator is the planned headcount — `capacity_youth` — even if fewer registrations exist. It is computed at registration creation and recomputed for every non-terminal registration (`DRAFT`, `SUBMITTED`, `APPROVED`, `WAITLISTED`, `CONFIRMED`) whenever the lodging total changes or `capacity_youth` is edited, but only while the trip is pre-lock (`DRAFT`, `REGISTRATION_OPEN`, or `REGISTRATION_CLOSED`).

The final share answers "what does each confirmed family actually owe?" and is computed exactly once, at roster lock. Let N be `confirmed_youth_count` (the lock is rejected at zero, so N is at least 1) and L the trip's `lodging_cost_total_cents`. The per-person lodging share is L divided by N, rounded half up; the signed remainder delta is L minus N times that share. The `CONFIRMED` registrations are ordered by the registration's `created_at` ascending with ties broken by the participant's `created_at` ascending, and the system walks that order applying one cent of delta per registration — in the sign of delta — until the remainder is exhausted; because the absolute remainder is smaller than N, each registration is touched at most once. The pinned order is round-then-sum: summing first and rounding once is a rejected alternative. Each registration's `final_cost_share_cents` is then `base_cost_cents` plus the share plus its adjustment (zero for most). Before the lock, `final_cost_share_cents` reads 0.

Deadlines are enforced by the delinquency sweep that runs whenever the logical clock advances. Sweep A targets the deposit milestone: for every registration in `APPROVED` or `CONFIRMED` whose trip's new clock reading is strictly past `deposit_due_at` and whose `covered_cents` is below `deposit_cents`, with no deposit late fee yet assessed, the registration moves to `DELINQUENT` and a late fee is added to `late_fees_total_cents`. Sweep B targets the final milestone: same statuses, clock strictly past `final_payment_due_at`, `amount_due_cents` still positive, and no final fee yet assessed. The fee in both cases is the greater of a 2500-cent flat amount and 5% of the `amount_due_cents` at sweep time, that percentage rounded half up to the nearest cent. Each milestone's fee is assessed at most once per registration — the `deposit_late_fee_assessed` and `final_late_fee_assessed` flags make repeated clock advances past the same deadline idempotent — but a registration that misses both deadlines collects two fees. A clock reading exactly equal to a deadline does not fire the sweep; the comparison is strictly greater.

A delinquent registration is cured by money, not by time. While the clock is at or before `final_payment_due_at`, posting enough to bring `covered_cents` to at least `deposit_cents` returns the registration to `PARTIALLY_PAID`; once the clock is past `final_payment_due_at`, only full coverage of the amount due cures — to `PAID_IN_FULL`. Covering the full amount due at any time (via payment, disbursement, or applied credit) moves a delinquent registration straight to `PAID_IN_FULL`.

### 3.7. Withdrawal, Dismissal, and Discipline

A guardian or director may withdraw a registration from any non-terminal status, with an optional `reason`. One hard rule: a `CONFIRMED` registration on a trip that is already `IN_PROGRESS` cannot withdraw — the only way out mid-trip is dismissal (`ERR_TRIP_STATE_FORBIDS_ACTION`). The cascade grows with the registration's maturity. From `DRAFT`, `SUBMITTED`, or `WAITLISTED`, withdrawal simply closes the `OPEN` fundraising account and voids every non-`VOIDED` consent form. From `APPROVED` or `CONFIRMED`, the cascade additionally auto-refunds every `POSTED` payment (flipping `payment_status` to `REFUNDED` when at least one payment refunded), moves the scholarship application through its hop (`UNDER_REVIEW` to `WITHDRAWN`, `APPROVED` to `RESCINDED`, `DISBURSED` to `RETURNED`, with the program fund triple recomputed at each hop), and recomputes the trip's `seats_taken`; from `CONFIRMED` it also recomputes `confirmed_youth_count` and re-evaluates `ratio_compliant`. If the trip is already `ROSTER_LOCKED`, the final shares are **not** recomputed — the lock is immutable — and the withdrawn registration keeps its recorded `final_cost_share_cents`.

Dismissal is the discipline instrument: a `ProgramDirector` may dismiss only a `CONFIRMED` registration, moving it to the terminal `DISMISSED` status, only while the trip is `IN_PROGRESS`, and must supply a `sanction` of `SENT_HOME` or `BARRED_FROM_FUTURE` (anything else is `ERR_INVALID_ENUM`) along with a `reason`. The sanction and rationale are recorded in `dismiss_sanction` and `dismiss_reason`; a `BARRED_FROM_FUTURE` sanction additionally sets the participant's `barred_until` to the current logical clock plus 730 days — two full screening cycles — which then blocks that participant from new registrations and approvals until it passes. The cascade closes the account and voids the forms as on withdrawal, moves scholarship applications `UNDER_REVIEW` to `WITHDRAWN` and `APPROVED` to `RESCINDED`, but retains a `DISBURSED` application — no clawback on dismissal. The trip's `confirmed_youth_count` is recomputed and `ratio_compliant` re-evaluated: a dismissal can flip a locked trip out of ratio compliance, which blocks nothing retroactively but is visible on reads. Unlike withdrawal, dismissal performs no payment auto-refund.

### 3.8. Chaperones, Screening, and Assignments

Chaperones are adults who supervise the trip. A `ProgramDirector` creates the record under a program with `first_name`, `last_name`, `email`, and `phone`; `current_screening_expires_at` starts empty and is thereafter the system's pointer to the `expires_at` of the chaperone's latest `CLEARED` background check.

Screening is a small lifecycle of its own, administered by the director. Initiating a background check — optionally with a `vendor_reference` — requires that the chaperone have no other check in `INITIATED` or `SCREENING` (`ERR_SCREENING_IN_PROGRESS_EXISTS`, HTTP 409); the new check is `INITIATED`. Advancing with `to_status` of `SCREENING` requires the check to be `INITIATED`; from `SCREENING`, the director advances either to `CLEARED` or to `FLAGGED` — any other reachability is `ERR_CHECK_STATE_FORBIDS_ACTION`, and an unrecognized `to_status` is `ERR_INVALID_ENUM`. A `CLEARED` outcome stamps `cleared_at` from the logical clock and computes `expires_at` as exactly 730 days after `cleared_at`, then recomputes the chaperone's `current_screening_expires_at` as the maximum `expires_at` over their `CLEARED` checks. A `FLAGGED` outcome cascades two hops: every assignment of this chaperone in `PROPOSED` or `CONFIRMED` is removed with `removal_reason` of `AUTO_SCREENING`, and for each affected trip the `cleared_chaperone_count` is recomputed and `ratio_compliant` re-evaluated, before the chaperone's screening pointer is recomputed. `FLAGGED` is terminal.

Screening also expires with time. When the logical clock advances to or past a `CLEARED` check's `expires_at`, the expiry sweep moves the check to `EXPIRED` (terminal) and cascades: every assignment of that chaperone in `PROPOSED` or `CONFIRMED` whose trip's end instant — midnight UTC on the day after the trip's `end_date` — is at or after the `expires_at` is removed with `removal_reason` of `AUTO_SCREENING`; the affected trips recompute cleared counts and ratio compliance; and the chaperone's screening pointer is recomputed.

Assignments bind a chaperone to a trip. A director or trip leader proposes one with `trip_id`, `chaperone_id`, and a `role` of `LEAD` or `SUPPORT`; the trip must be in `DRAFT`, `REGISTRATION_OPEN`, `REGISTRATION_CLOSED`, or `ROSTER_LOCKED` (`ERR_TRIP_STATE_FORBIDS_ACTION`). The safety gate runs before the constraint gates: the chaperone must hold a `CLEARED` background check whose `expires_at` is at or after the trip's end instant — valid *through* the trip, boundary inclusive — else `ERR_SCREENING_NOT_VALID_THROUGH_TRIP` (HTTP 422). Then the uniqueness constraints: at most one assignment with `role` of `LEAD` per trip among `PROPOSED` and `CONFIRMED` (`ERR_DUPLICATE_LEAD_CHAPERONE`, HTTP 409); no other non-terminal assignment for the same (trip, chaperone) pair (`ERR_DUPLICATE_ASSIGNMENT`, HTTP 409); and no overlap with another trip — if the chaperone is already `PROPOSED` or `CONFIRMED` on a trip whose closed date interval (start date through end date, inclusive of both boundary dates) intersects this trip's, the proposal is `ERR_CHAPERONE_TRIP_OVERLAP` (HTTP 409), and note that merely sharing a boundary date does conflict. A valid proposal is `PROPOSED`.

The assigned chaperone — and only that chaperone, matched by `X-User-ID` against the assignment's `chaperone_id` (`ERR_NOT_RESOURCE_OWNER`) — responds: `decision` of `ACCEPT` confirms the assignment, recomputing the trip's cleared count and ratio compliance; `decision` of `DECLINE` moves it to `DECLINED`, terminal. Responding to an assignment not `PROPOSED` is `ERR_ASSIGNMENT_STATE_FORBIDS_ACTION`. A director or trip leader may remove a `PROPOSED` or `CONFIRMED` assignment (optionally with a `reason`); manual removal records `removal_reason` of `MANUAL`, recomputes the trip counts, and leaves `REMOVED` terminal. The `AUTO_SCREENING` value appears only on system removals.

The ratio rule ties the roster together: `required_cleared_chaperones` is `confirmed_youth_count` divided by the trip's `chaperone_ratio`, rounded up to a whole number (an exact multiple of the ratio needs no extra chaperone); `cleared_chaperone_count` counts `CONFIRMED` assignments whose chaperone's `CLEARED` check has `expires_at` at or after the trip end instant; and `ratio_compliant` holds when the cleared count is at least the requirement. This rule is recomputed on every mutation touching the confirmed-youth count, the ratio, the confirmed-assignment set, or the cleared-check set — which is why confirms, withdrawals, dismissals, assignment responses, removals, screening outcomes, and clock sweeps all ripple into it.

### 3.9. Itinerary and Lodging

Trip logistics content is the `TripLeader`'s domain. Itinerary items may be added while the trip is in `DRAFT`, `REGISTRATION_OPEN`, `REGISTRATION_CLOSED`, or `ROSTER_LOCKED` (`ERR_TRIP_STATE_FORBIDS_ACTION` once the trip is underway). Each item carries a `segment_type` of `TRAVEL`, `LODGING`, `SERVICE`, `MEAL`, or `FREE`, a `title`, `start_at` and `end_at` instants, an optional `location` (defaulting to empty), and a `vehicle_code` that is required exactly when the segment type is `TRAVEL` and otherwise defaults to empty. Two temporal rules apply: the item must begin before it ends (`ERR_INVALID_DATE_RANGE`), and both endpoints must sit inside the trip window — from midnight UTC on `start_date` up to but not including midnight UTC on the day after `end_date` (`ERR_ITINERARY_OUTSIDE_TRIP_WINDOW`, HTTP 422). Vehicles need turnaround time: two `TRAVEL` items sharing a `vehicle_code` must leave at least a 45-minute gap between one item's end and the other's start — intervals that merely touch violate the buffer and are rejected with `ERR_VEHICLE_SCHEDULE_CONFLICT` (HTTP 409).

Lodging reservations book room blocks while the trip is pre-lock (`DRAFT`, `REGISTRATION_OPEN`, or `REGISTRATION_CLOSED`). A reservation names a `site_name`, a `room_code`, `check_in_date` and `check_out_date` (check-out strictly after check-in, else `ERR_INVALID_DATE_RANGE`), a `room_capacity` of at least 1 bed, and a `cost_cents` of zero or more. Rooms are single-occupancy resources: a new reservation whose half-open stay interval — check-in day inclusive through check-out day exclusive — overlaps an existing `CONFIRMED` reservation with the same (trip, `site_name`, `room_code`) is rejected with `ERR_ROOM_ALREADY_BOOKED` (HTTP 409); a back-to-back booking where one room's check-out equals the next's check-in is allowed. A created reservation is `CONFIRMED` and immediately feeds the trip's `lodging_cost_total_cents` — the sum of `cost_cents` over `CONFIRMED` reservations — which in turn recomputes the provisional share of every non-terminal registration while the trip is pre-lock. A `TripLeader` may cancel a `CONFIRMED` reservation (optionally with a `reason`) while the trip remains pre-lock; logistics are frozen from `ROSTER_LOCKED` onward (`ERR_TRIP_STATE_FORBIDS_ACTION`), and cancelling anything not `CONFIRMED` is `ERR_LODGING_STATE_FORBIDS_ACTION`. Cancellation moves the reservation to `CANCELLED`, recomputes the lodging rollup, and recomputes pre-lock provisional shares and amounts due across the roster.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, drive a state transition, or run a capability return `200 OK` (the logical-clock set returns `200` with an empty data object). The complete surface is listed below; request payloads and side effects are specified in §3 and the error catalogue in §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/youth-ministry/_clock/set-current-utc` | Advance the logical clock; runs delinquency and screening-expiry sweeps | ProgramDirector |
| POST | `/youth-ministry/programs` | Create a youth program (starts OPEN) | ProgramDirector |
| GET | `/youth-ministry/programs/{id}` | Read one program including the scholarship fund triple and policy | ProgramDirector, TripLeader, Treasurer, ScholarshipReviewer, Guardian, Chaperone |
| PUT | `/youth-ministry/programs/{id}/scholarship-policy` | Replace scholarship award policy (OCC-guarded) | ProgramDirector |
| POST | `/youth-ministry/programs/{id}/close` | Close the program; requires every trip DEBRIEFED or CANCELLED | ProgramDirector |
| POST | `/youth-ministry/trips` | Create a trip in DRAFT under a program | ProgramDirector |
| GET | `/youth-ministry/trips` | List trips; optional `program_id`, `status` filters | ProgramDirector, TripLeader, Treasurer, ScholarshipReviewer, Guardian, Chaperone |
| GET | `/youth-ministry/trips/{id}` | Read one trip including computed roster/ratio/lodging fields | ProgramDirector, TripLeader, Treasurer, ScholarshipReviewer, Guardian, Chaperone |
| PATCH | `/youth-ministry/trips/{id}` | Edit trip logistics fields (OCC-guarded) | ProgramDirector |
| POST | `/youth-ministry/trips/{id}/open-registration` | Transition DRAFT to REGISTRATION_OPEN | ProgramDirector |
| POST | `/youth-ministry/trips/{id}/close-registration` | Transition REGISTRATION_OPEN to REGISTRATION_CLOSED | ProgramDirector |
| POST | `/youth-ministry/trips/{id}/lock-roster` | Lock the roster; runs the full gate chain and computes final cost shares | ProgramDirector |
| POST | `/youth-ministry/trips/{id}/start` | Transition ROSTER_LOCKED to IN_PROGRESS | ProgramDirector |
| POST | `/youth-ministry/trips/{id}/debrief` | Transition IN_PROGRESS to DEBRIEFED; records the post-trip report | ProgramDirector |
| POST | `/youth-ministry/trips/{id}/cancel` | Cancel a trip from any non-terminal state; branch-dependent cascade | ProgramDirector |
| POST | `/youth-ministry/participants` | Register a youth participant | ProgramDirector, Guardian |
| GET | `/youth-ministry/participants` | List participants; optional `program_id`, `family_key` filters | ProgramDirector, TripLeader, Treasurer |
| GET | `/youth-ministry/participants/{id}` | Read one participant (Guardian limited to own) | ProgramDirector, TripLeader, Treasurer, Guardian |
| POST | `/youth-ministry/registrations` | Create a registration (DRAFT / PENDING_DEPOSIT) and auto-open its fundraising account | ProgramDirector, Guardian |
| GET | `/youth-ministry/registrations` | List registrations; optional `trip_id`, `participant_id`, `registration_status`, `payment_status` filters | ProgramDirector, TripLeader, Treasurer |
| GET | `/youth-ministry/registrations/{id}` | Read one registration (Guardian limited to own) | ProgramDirector, TripLeader, Treasurer, ScholarshipReviewer, Guardian |
| POST | `/youth-ministry/registrations/{id}/submit` | Transition DRAFT to SUBMITTED; requires the three required forms | ProgramDirector, Guardian |
| POST | `/youth-ministry/registrations/{id}/review` | Approve (capacity fork to APPROVED or WAITLISTED) or reject a SUBMITTED registration | ProgramDirector, TripLeader |
| POST | `/youth-ministry/registrations/{id}/promote` | Promote the waitlist head to APPROVED while seats remain | ProgramDirector, TripLeader |
| POST | `/youth-ministry/registrations/{id}/confirm` | Transition APPROVED to CONFIRMED; requires deposit coverage | ProgramDirector |
| POST | `/youth-ministry/registrations/{id}/withdraw` | Withdraw a registration from any non-terminal status | ProgramDirector, Guardian |
| POST | `/youth-ministry/registrations/{id}/dismiss` | Dismiss a CONFIRMED registration during an IN_PROGRESS trip | ProgramDirector |
| POST | `/youth-ministry/registrations/{id}/consent-forms` | Submit a consent/medical/media/conduct form | ProgramDirector, Guardian |
| GET | `/youth-ministry/registrations/{id}/consent-forms` | List consent forms of a registration (Guardian limited to own) | ProgramDirector, TripLeader, Guardian |
| POST | `/youth-ministry/consent-forms/{id}/review` | Verify or reject a SUBMITTED consent form | ProgramDirector, TripLeader |
| POST | `/youth-ministry/consent-forms/{id}/resubmit` | Resubmit a REJECTED consent form with corrected content | ProgramDirector, Guardian |
| POST | `/youth-ministry/registrations/{id}/payments` | Post a payment against an APPROVED or CONFIRMED registration | Treasurer, Guardian |
| GET | `/youth-ministry/registrations/{id}/payments` | List payments of a registration (Guardian limited to own) | ProgramDirector, Treasurer, Guardian |
| POST | `/youth-ministry/payments/{id}/refund` | Refund a POSTED payment | Treasurer |
| GET | `/youth-ministry/registrations/{id}/fundraising-account` | Read the one-to-one fundraising account of a registration | ProgramDirector, Treasurer, Guardian |
| GET | `/youth-ministry/fundraising-accounts/{id}` | Read one fundraising account with all rollups | ProgramDirector, Treasurer, Guardian |
| POST | `/youth-ministry/fundraising-accounts/{id}/donations` | Record a donation (RECEIVED); fee computed per channel | Treasurer |
| GET | `/youth-ministry/fundraising-accounts/{id}/donations` | List donations of an account | ProgramDirector, Treasurer |
| POST | `/youth-ministry/donations/{id}/refund` | Refund a RECEIVED donation | Treasurer |
| POST | `/youth-ministry/fundraising-accounts/{id}/apply-credit` | Move the full available net credit onto the registration balance | Treasurer |
| POST | `/youth-ministry/scholarship-applications` | Apply for scholarship for an APPROVED or CONFIRMED registration | ProgramDirector, Guardian |
| GET | `/youth-ministry/scholarship-applications` | List applications; optional `registration_id`, `status` filters | ProgramDirector, ScholarshipReviewer, Treasurer |
| GET | `/youth-ministry/scholarship-applications/{id}` | Read one application (Guardian limited to own registration's) | ProgramDirector, ScholarshipReviewer, Treasurer, Guardian |
| POST | `/youth-ministry/scholarship-applications/{id}/decide` | Approve (computes award, reserves fund) or deny an UNDER_REVIEW application | ScholarshipReviewer |
| POST | `/youth-ministry/scholarship-applications/{id}/appeal` | Return a DENIED application to UNDER_REVIEW | ProgramDirector, Guardian |
| POST | `/youth-ministry/scholarship-applications/{id}/disburse` | Disburse an APPROVED application; segregated from the approver | Treasurer |
| POST | `/youth-ministry/scholarship-applications/{id}/rescind` | Rescind an APPROVED application; releases the reservation | ScholarshipReviewer |
| POST | `/youth-ministry/chaperones` | Create a chaperone record | ProgramDirector |
| GET | `/youth-ministry/chaperones` | List chaperones; optional `program_id` filter | ProgramDirector, TripLeader |
| GET | `/youth-ministry/chaperones/{id}` | Read one chaperone (Chaperone limited to own record) | ProgramDirector, TripLeader, Chaperone |
| POST | `/youth-ministry/chaperones/{id}/background-checks` | Initiate a background check (INITIATED) | ProgramDirector |
| GET | `/youth-ministry/chaperones/{id}/background-checks` | List background checks of a chaperone (Chaperone limited to own) | ProgramDirector, TripLeader, Chaperone |
| POST | `/youth-ministry/background-checks/{id}/advance` | Advance a check to SCREENING, CLEARED, or FLAGGED | ProgramDirector |
| POST | `/youth-ministry/chaperone-assignments` | Propose a chaperone for a trip (PROPOSED) | ProgramDirector, TripLeader |
| GET | `/youth-ministry/chaperone-assignments` | List assignments; optional `trip_id`, `chaperone_id`, `status` filters (Chaperone sees only own) | ProgramDirector, TripLeader, Chaperone |
| GET | `/youth-ministry/chaperone-assignments/{id}` | Read one assignment (Chaperone limited to own) | ProgramDirector, TripLeader, Chaperone |
| POST | `/youth-ministry/chaperone-assignments/{id}/respond` | Accept or decline a PROPOSED assignment | Chaperone |
| POST | `/youth-ministry/chaperone-assignments/{id}/remove` | Remove a PROPOSED or CONFIRMED assignment | ProgramDirector, TripLeader |
| POST | `/youth-ministry/trips/{id}/itinerary-items` | Add an itinerary item while the trip is pre-IN_PROGRESS | TripLeader |
| GET | `/youth-ministry/trips/{id}/itinerary-items` | List itinerary items of a trip | ProgramDirector, TripLeader, Chaperone |
| POST | `/youth-ministry/trips/{id}/lodging-reservations` | Book a room block (CONFIRMED) while the trip is pre-lock | TripLeader |
| GET | `/youth-ministry/trips/{id}/lodging-reservations` | List lodging reservations of a trip | ProgramDirector, TripLeader |
| POST | `/youth-ministry/lodging-reservations/{id}/cancel` | Cancel a CONFIRMED lodging reservation while the trip is pre-lock | TripLeader |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ENUM` | 400 Bad Request |
| `ERR_INVALID_DATE_RANGE` | 400 Bad Request |
| `ERR_ROLE_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_TRIP_NOT_FOUND` | 404 Not Found |
| `ERR_PARTICIPANT_NOT_FOUND` | 404 Not Found |
| `ERR_REGISTRATION_NOT_FOUND` | 404 Not Found |
| `ERR_CONSENT_FORM_NOT_FOUND` | 404 Not Found |
| `ERR_FUNDRAISING_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_DONATION_NOT_FOUND` | 404 Not Found |
| `ERR_PAYMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SCHOLARSHIP_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_CHAPERONE_NOT_FOUND` | 404 Not Found |
| `ERR_BACKGROUND_CHECK_NOT_FOUND` | 404 Not Found |
| `ERR_CHAPERONE_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_LODGING_RESERVATION_NOT_FOUND` | 404 Not Found |
| `ERR_PROGRAM_NOT_OPEN` | 409 Conflict |
| `ERR_PROGRAM_HAS_OPEN_TRIPS` | 409 Conflict |
| `ERR_TRIP_STATE_FORBIDS_ACTION` | 409 Conflict |
| `ERR_REGISTRATION_STATE_FORBIDS_ACTION` | 409 Conflict |
| `ERR_CONSENT_FORM_STATE_FORBIDS_ACTION` | 409 Conflict |
| `ERR_APPLICATION_STATE_FORBIDS_ACTION` | 409 Conflict |
| `ERR_CHECK_STATE_FORBIDS_ACTION` | 409 Conflict |
| `ERR_ASSIGNMENT_STATE_FORBIDS_ACTION` | 409 Conflict |
| `ERR_DONATION_STATE_FORBIDS_ACTION` | 409 Conflict |
| `ERR_PAYMENT_STATE_FORBIDS_ACTION` | 409 Conflict |
| `ERR_LODGING_STATE_FORBIDS_ACTION` | 409 Conflict |
| `ERR_ACCOUNT_CLOSED` | 409 Conflict |
| `ERR_PARTICIPANT_BARRED` | 409 Conflict |
| `ERR_SCREENING_NOT_VALID_THROUGH_TRIP` | 422 Unprocessable Entity |
| `ERR_CHAPERONE_RATIO_UNMET` | 422 Unprocessable Entity |
| `ERR_INSURANCE_TIER_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_REQUIRED_FORMS_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_REGISTRATION_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_ITINERARY_OUTSIDE_TRIP_WINDOW` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_REGISTRATION` | 409 Conflict |
| `ERR_DUPLICATE_CONSENT_FORM_TYPE` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_APPLICATION` | 409 Conflict |
| `ERR_SCREENING_IN_PROGRESS_EXISTS` | 409 Conflict |
| `ERR_DUPLICATE_LEAD_CHAPERONE` | 409 Conflict |
| `ERR_DUPLICATE_ASSIGNMENT` | 409 Conflict |
| `ERR_ROOM_ALREADY_BOOKED` | 409 Conflict |
| `ERR_VEHICLE_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_CHAPERONE_TRIP_OVERLAP` | 409 Conflict |
| `ERR_CAPACITY_FLOOR` | 409 Conflict |
| `ERR_WAITLIST_NOT_HEAD` | 409 Conflict |
| `ERR_NO_WAITLIST_CAPACITY` | 409 Conflict |
| `ERR_EMPTY_ROSTER` | 422 Unprocessable Entity |
| `ERR_EMERGENCY_PROTOCOL_MISSING` | 422 Unprocessable Entity |
| `ERR_LODGING_CAPACITY_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_DEPOSIT_NOT_COVERED` | 402 Payment Required |
| `ERR_UNPAID_BALANCES_REMAIN` | 402 Payment Required |
| `ERR_SCHOLARSHIP_FUND_EXHAUSTED` | 402 Payment Required |
| `ERR_AWARD_WOULD_BE_ZERO` | 422 Unprocessable Entity |
| `ERR_NO_CREDIT_AVAILABLE` | 422 Unprocessable Entity |
| `ERR_STALE_PROGRAM_VERSION` | 412 Precondition Failed |
| `ERR_STALE_TRIP_VERSION` | 412 Precondition Failed |
