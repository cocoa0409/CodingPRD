# Community Cat TNR Program API — Product Requirements Document

## 1. Introduction

Feral and free-roaming cat colonies are a standing concern for municipalities: unchecked breeding drives neighbor complaints, and ad-hoc trapping efforts rarely produce measurable population decline. A trap-neuter-return (TNR) program attacks the problem systematically — colonies are registered under responsible caretakers, cats are trapped on schedule, sterilized and vaccinated at partner clinics, ear-tipped so their status is visible in the field, and returned to their territory; kittens and socializable adults are routed toward adoption instead. Coordinating that work across caretakers, clinics, animal control officers, and foster volunteers on spreadsheets produces double-booked clinic days, lapsed vouchers, and colonies whose sterilization progress nobody can quantify.

This document specifies the Community Cat TNR Program API, the system of record for one such municipal program. It governs colony registration and caretaker assignment, clinic day scheduling and slot allocation, trapping appointment booking, surgery recording with ear-tip and rabies capture, the post-surgery disposition decision between return-to-field and adoption, a kitten foster network for the spring capacity surge, neighbor complaint intake and mediation, a voucher-based funding program with monthly issuance caps and clinic reimbursement, and longitudinal population monitoring with trend reporting. Authority is deliberately partitioned across five operator roles — only clinic personnel record surgery outcomes, only caretakers book and run trapping appointments, and only the program coordinator decides a cat's final pathway — so that the audit trail for every animal is unambiguous.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, representations, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the capacity in which they act. The system recognizes exactly five roles: `ProgramCoordinator` (municipal program staff), `Caretaker` (registered colony caretaker), `ClinicStaff` (partner clinic personnel), `AnimalControlOfficer` (field officer for neighbor complaints), and `FosterVolunteer` (foster home operator). A request missing either header, or presenting a role outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A well-identified caller attempting an operation not granted to their role is rejected with `ERR_FORBIDDEN` (HTTP 403). Authentication is always evaluated before authorization, and authorization before any resource lookup.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Caretaker`, `X-User-ID` is the `id` of the acting `Caretaker` record; ownership checks on any resource that references a caretaker — a colony's registered caretaker or a voucher's holder — compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `FosterVolunteer`, `X-User-ID` is the `id` of the acting `FosterHome`; ownership checks on a foster placement compare the placement's home reference to `X-User-ID`. When `X-User-Role` is `ProgramCoordinator`, `ClinicStaff`, or `AnimalControlOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the server never compares it against any entity's `id`.

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

List endpoints accept two query parameters. `limit` caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items from the front of the result set and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Program's Logical Clock

The server keeps a logical clock that governs every timestamp it stamps and every temporal rule it evaluates. Before the clock has ever been set, it reads exactly 2026-08-01T00:00:00Z, and it must never fall back to wall-clock time. A `ProgramCoordinator`-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant and responds 200 OK; every server-stamped timestamp after that call uses the new logical time.

The logical clock stamps a colony's `registered_on`, a complaint's `filed_at`, a surgery record's `performed_at`, a foster placement's `placed_at`, and a voucher's `issued_month` — the year-and-month of issuance in `YYYY-MM` form, which drives the monthly issuance cap of §2.8. Temporal validations — a trapping date that must precede its clinic day, a clinic day that may not be scheduled in the past, a survey that may not be dated in the future, and the three-month voucher age threshold of §3.8 — are all evaluated against the logical clock, never against real time. A clinic day's `service_date` is compared as a calendar date; any time component is ignored.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` — a server-minted UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` — an integer that increments by one on every mutation, including mutations caused by side effects and by recomputation of derived fields; it backs the optimistic concurrency checks of §2.9.

`PopulationSurvey` is the single exception: as an append-only field observation it carries only `id` and `created_at`; `updated_at` and `version` are absent from it.

### 2.6. Colony Sterilization Rate and Monitoring Posture

Each colony continuously exposes two derived fields that summarize program progress. `sterilized_pct` is the fraction of the colony's resident cats whose `status` is `RETURNED` or `COLONY_STERILIZED`. The resident set comprises the colony's cats standing in any of `AT_LARGE`, `TRAPPED`, `AT_CLINIC`, `POST_SURGERY`, `RETURNED`, `COLONY_STERILIZED`, `IN_FOSTER`, or `ADOPTION_PIPELINE`; cats that are `ADOPTED` or `DECEASED` leave the resident set entirely. When a colony has no resident cats, `sterilized_pct` is 0. The fraction is rounded half-up to four decimal places. Because `IN_FOSTER` and `ADOPTION_PIPELINE` cats sit in the denominator but never the numerator, kittens awaiting adoption depress the rate until they resolve.

`monitoring_status` summarizes the colony's posture in one of three values. A colony is `STABLE` when its sterilized fraction is at least 0.75 and no complaint against it stands `OPEN`. It is `WATCH` when the sterilized fraction reaches that same three-quarter threshold but at least one complaint stands `OPEN`. In every other case the colony is `ACTIVE`, which is also its posture at registration. Only `OPEN` complaints participate in this rule — complaints in `IN_MEDIATION`, `ESCALATED`, or `RESOLVED` do not block `STABLE`.

Both derivations are recomputed eagerly: on every transition that changes a resident cat's status-set membership (surgery completion, a return-to-field decision, an adoption finalization, a foster return), on cat intake, and on every complaint status change. Recomputation is a mutation of the colony even when the numbers do not change — `updated_at` is refreshed and `version` increments.

### 2.7. Clinic Day Capacity and the Kitten-Season Surge

A clinic day is created with `base_capacity` normal surgery slots plus `surge_capacity` additional slots held for the spring kitten season; `booked_count` tracks how many of the day's slots currently stand `BOOKED`. Whether one more booking is admitted depends on both the calendar and the cat. During kitten season — the months of March through July — a booking for a kitten (a cat whose `approximate_age_months` is under six, surfaced as the derived `is_kitten` flag) is admitted while `booked_count` is strictly less than the sum of `base_capacity` and `surge_capacity`. In every other case — an adult cat in any month, or any cat outside the season — the booking is admitted only while `booked_count` is strictly less than `base_capacity`; surge slots are unreachable for adult bookings. The comparison is a strict less-than on integers: a booking that would bring `booked_count` from one below the applicable limit up to that limit succeeds, while a booking made when `booked_count` already equals the applicable limit is rejected with `ERR_CLINIC_DAY_FULL` (HTTP 409) — even if surge slots sit unused on the day.

`booked_count` increments by one when a slot is booked and decrements by one when a surgery is completed or an appointment is cancelled. The end-of-day no-show sweep of §3.2 consumes booked slots without decrementing the count, since the day is closing and the count no longer gates anything.

### 2.8. Voucher Funding, Issuance Cap, and Reimbursement

Vouchers draw on one of two budget lines, recorded in `funding_source` as `MUNICIPAL_GRANT` or `DONATION_FUND`. Issuance is capped per caretaker and calendar month: the program issues at most 30,000 cents — three hundred dollars — of vouchers to one caretaker within a single `issued_month`, across both funding sources combined. The caretaker's consumed envelope is the sum of `face_value_cents` over their vouchers stamped with the current logical month whose `status` is `ISSUED`, `COMMITTED`, or `REDEEMED`. `VOIDED` and `EXPIRED` vouchers do not consume the envelope, so a caretaker whose voucher died in surgery can re-issue within the same month up to the cap. An issuance request whose `face_value_cents` exceeds the remaining headroom is rejected with `ERR_MONTHLY_CAP_EXCEEDED` (HTTP 402); a request that lands exactly on the cap is admitted, since only a strict excess is rejected. All voucher arithmetic is integer cents.

Reimbursement settles when a committed voucher is redeemed at surgery completion. The payable base is the smaller of the voucher's `face_value_cents` and the hosting clinic's `voucher_reimbursement_cents`. A municipal-grant voucher reimburses the clinic the full base, and the caretaker owes nothing. A donation-fund voucher reimburses the clinic 80 percent of the base, rounded down to a whole cent, and the caretaker is invoiced the remainder; the downward rounding guarantees the clinic reimbursement plus the caretaker share equals the base exactly. A surgery ending in mortality redeems nothing: the voucher is voided and no reimbursement is made.

### 2.9. Optimistic Concurrency Control

Exactly two write operations are guarded by optimistic concurrency. Booking a trapping appointment requires the client to submit `expected_clinic_day_version`, carrying the `version` of the hosting clinic day as the client last observed it; if another booking or release has advanced the day's version since that read, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), so a client never books against a capacity view it has not observed. Deciding a cat's pathway requires `expected_cat_version`, compared against the cat's current `version`; if a foster return or another pathway decision has advanced the cat since the client's last read — re-opening the decision by resetting `pathway` — the request is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). Both fields are non-optional on their respective endpoints. No other endpoint accepts a version field.

### 2.10. Nested Resource Retrieval and Validation Order

Requests that address nested resources are validated left-to-right: each identifier in the path is resolved in turn, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing record. Foreign keys supplied in the request body are resolved after the path identifiers, in their declared order. Existence always precedes state: a transition requested against a missing resource yields 404, never a state error.

Across a full request, the validation classes run in a fixed order — authentication, then authorization, then existence, then state-transition legality (a transition that does not exist from the entity's current state is rejected with `ERR_INVALID_STATE`, HTTP 409), then the optimistic concurrency check of §2.9, and finally the endpoint's business rules in the orders given throughout §3.

### 2.11. Population Trend Classification

The population report classifies a colony's trend from its field surveys. Surveys are processed in chronological order by `surveyed_on`, with same-day surveys tie-broken by `created_at` ascending — never by `id` — because two valid orderings of disagreeing same-day surveys produce different labels, so the order is pinned here. A colony with fewer than two surveys reports `INSUFFICIENT_DATA`. Otherwise the change is measured from the first survey's `observed_count` to the last survey's `observed_count`, as the difference divided by the first count. The ratio is compared unrounded against two thresholds: a decline of 20 percent or more — that is, a ratio of −0.20 or lower — classifies the colony `DECLINING`; growth of 20 percent or more — a ratio of +0.20 or higher — classifies it `GROWING`; anything strictly between the two is `FLAT`. Both thresholds are inclusive. A zero baseline is a pinned special case rather than an error: when the first survey observed zero cats, the colony is `GROWING` if the latest survey observed any cats at all and `FLAT` if it also observed zero.

## 3. Business Logic & Workflows

### 3.1. Onboarding Caretakers, Colonies, and Cats

Program onboarding begins with the people. A `ProgramCoordinator` registers each caretaker with a `full_name`, a free-form contact `phone`, and a contact `email`; the `email` must be unique across all caretakers, and a duplicate is rejected with `ERR_UNIQUENESS_VIOLATION` (HTTP 409). Registration also records whether the caretaker completed the municipal TNR certification course via `certified_tnr`, which defaults to false when omitted. A caretaker account's standing is tracked in `status` as `ACTIVE` or `SUSPENDED` and begins `ACTIVE`.

Colonies come next. A `ProgramCoordinator` registers a colony with a human-readable `name` (for example, "Boardwalk behind pier 9"), a street address or parcel description in `address`, the `caretaker_id` of the registered primary caretaker, and the caretaker's initial head-count estimate in `estimated_population`, which must be at least 1. The server stamps `registered_on` from the logical clock, initializes `monitoring_status` to `ACTIVE`, and sets the colony lifecycle `status` to `REGISTERED`. The roster of colonies can be listed and filtered by `caretaker_id` or by `monitoring_status`, and fetching a single colony always includes the live `sterilized_pct` and `monitoring_status` derivations of §2.6.

Cats are added to a colony by the `ProgramCoordinator` or by a `Caretaker`. Intake happens under the colony's own address, and the new cat carries that colony's `colony_id`. Intake captures a human-assigned `intake_tag` — a trap log number or similar — which must be unique within its colony, with duplicates rejected by `ERR_UNIQUENESS_VIOLATION`; a `sex` of `MALE`, `FEMALE`, or `UNKNOWN`; and an `approximate_age_months` estimate in whole months, zero or greater. From the age the server derives `is_kitten`, true when the cat is younger than six months. A new cat starts `AT_LARGE`, with `ear_tipped` and `vaccinated_rabies` both false and `pathway` unset (null). Every intake enlarges the colony's resident set, so `sterilized_pct` and `monitoring_status` are recomputed. The cats of a colony can be listed with a `status` filter, and any role may fetch an individual cat.

### 3.2. Partner Clinics and Clinic Day Operations

Surgical capacity enters the system through partner clinics. A `ProgramCoordinator` onboards a clinic with its business `name`, the per-voucher reimbursement amount `voucher_reimbursement_cents` — strictly greater than zero — and an `accepts_vouchers` flag that defaults to true. A clinic's onboarding `status` is `ACTIVE` or `INACTIVE`, beginning `ACTIVE`. The days a clinic hosts can be listed with a `status` filter.

`ClinicStaff` schedule surgery days. Scheduling names the hosting `clinic_id`, the calendar `service_date`, and the day's `base_capacity` of at least 1; `surge_capacity` may be added for the kitten season and defaults to 0 when omitted. A `service_date` in the past relative to the logical clock is rejected with `ERR_TEMPORAL_CONFLICT` (HTTP 422). On creation the server materializes the day's full slot inventory — `base_capacity` plus `surge_capacity` `ClinicSlot` rows, each recorded against the day's `clinic_day_id`, each standing `OPEN`, and each assigned a sequential `slot_index` starting at 1 — and the day begins `SCHEDULED` with `booked_count` at 0. Fetching the day exposes the live `booked_count`, and its slots can be listed with a `status` filter.

Two role-secured actions close out a day, and both require it to still stand `SCHEDULED`. Cancelling a day is permitted only while nothing is booked: with `booked_count` above zero the cancellation is rejected with `ERR_DAY_HAS_BOOKINGS` (HTTP 409); otherwise every `OPEN` slot becomes `RELEASED` and the day becomes `CANCELLED`. Closing a day performs the end-of-day sweep: every `BOOKED` slot whose appointment still stands `SCHEDULED` is consumed — the slot becomes `USED`, the appointment becomes `NO_SHOW`, a voucher committed on such an appointment is released back from `COMMITTED` to `ISSUED`, and the cat simply remains `AT_LARGE` — while every remaining `OPEN` slot becomes `RELEASED` and the day becomes `COMPLETED`. The sweep does not decrement `booked_count` for the slots it consumes, per §2.7.

### 3.3. Booking and Running Trapping Appointments

The appointment is the workhorse that binds a cat, a clinic slot, and optionally a voucher. A `Caretaker` books one by supplying the `cat_id` of the cat to be trapped, the `clinic_slot_id` to reserve, the planned `trap_date`, and — per §2.9 — the `expected_clinic_day_version` of the hosting day. An optional `voucher_id` commits program funding to the appointment; omitting it (null) means the clinic bills full price. A successfully created appointment stands `SCHEDULED`.

Booking enforces its checks in a fixed order. Existence comes first — the cat, the slot, and any voucher must all resolve, else `ERR_NOT_FOUND`. Then state: the slot must stand `OPEN` and its day still `SCHEDULED`, else `ERR_INVALID_STATE`. Then the concurrency check of §2.9. Then ownership: a voucher named on the booking must belong to the acting caretaker, else `ERR_OWNERSHIP_MISMATCH` (HTTP 403). Then the temporal rule: `trap_date` must fall strictly before the slot's clinic day `service_date`, else `ERR_TEMPORAL_CONFLICT`. Then the capacity guard of §2.7, rejected with `ERR_CLINIC_DAY_FULL` when the day is full for this booking's class. Finally the voucher itself must be usable: it must stand `ISSUED`, and the clinic hosting the day must accept vouchers, else `ERR_VOUCHER_NOT_USABLE` (HTTP 402). A successful booking flips the slot from `OPEN` to `BOOKED`, increments the day's `booked_count` and the day's `version`, and moves a committed voucher from `ISSUED` to `COMMITTED`.

Field execution proceeds in two role-separated steps. Once the cat is in the trap, the colony's own `Caretaker` confirms the trapping: the appointment must still stand `SCHEDULED`, it must reference this cat, and the cat must still stand `AT_LARGE`; the acting caretaker must be the registered caretaker of the cat's colony, with a mismatch rejected by `ERR_OWNERSHIP_MISMATCH`, while a repeated or out-of-turn confirmation fails with `ERR_INVALID_STATE`. Confirmation moves the appointment from `SCHEDULED` to `TRAPPED` and the cat from `AT_LARGE` to `TRAPPED`, and refreshes the colony's derived fields — the numbers do not change, but the recomputation still updates the colony per §2.6. On arrival at the clinic, `ClinicStaff` check the cat in: the appointment must stand `TRAPPED`, its slot must stand `BOOKED`, and the clinic day must still stand `SCHEDULED`. Check-in moves the cat from `TRAPPED` to `AT_CLINIC` and touches no other entity — the appointment itself remains `TRAPPED` until surgery completes it.

A caretaker may also cancel an appointment, but only while it stands `SCHEDULED` and only for a cat of their own colony — a cancellation attempted by anyone else is rejected with `ERR_OWNERSHIP_MISMATCH`. Cancellation releases the slot from `BOOKED` to `RELEASED`, decrements the day's `booked_count`, returns a committed voucher from `COMMITTED` to `ISSUED`, and marks the appointment `CANCELLED`. Appointments remain traceable from every angle: a cat's appointment history is listable with a `status` filter, as are the appointments booked against a given slot and the appointments that committed a given voucher.

### 3.4. Recording Surgery Outcomes

Surgery is recorded by `ClinicStaff` against a checked-in appointment, supplying the `appointment_id`, the recording surgeon's `surgeon_initials`, whether the left ear was tipped in `ear_tipped`, whether rabies vaccine was administered in `rabies_vaccinated`, an optional `complications` flag defaulting to false, and the `outcome` — one of `STERILIZED`, `ALREADY_STERILE`, or `DIED_IN_SURGERY`. The server stamps `performed_at` from the logical clock. The appointment must stand `TRAPPED` and must reference the cat, and the cat must stand `AT_CLINIC`; otherwise the record is rejected with `ERR_INVALID_STATE`. An appointment's surgery history remains listable.

A surviving outcome — `STERILIZED` or `ALREADY_STERILE` — moves the cat from `AT_CLINIC` to `POST_SURGERY` and copies the record's markers onto the cat: the cat's `ear_tipped` and `vaccinated_rabies` become exactly what the surgeon recorded. The appointment completes (`TRAPPED` to `COMPLETED`), its slot is consumed (`BOOKED` to `USED`), the day's `booked_count` decrements by one, and a voucher committed on the appointment is redeemed (`COMMITTED` to `REDEEMED`), settling the reimbursement of §2.8 — recorded against the budget line named by the voucher's `funding_source` — with the clinic that hosted the day. The colony's sterilization fraction and posture are recomputed.

A fatal outcome — `DIED_IN_SURGERY` — moves the cat from `AT_CLINIC` to `DECEASED` instead. The appointment still completes and the slot is still consumed with the day's `booked_count` decrementing, but a committed voucher is voided (`COMMITTED` to `VOIDED`) and no reimbursement is made on a mortality. The colony's derived fields are recomputed, the deceased cat having left the resident set.

### 3.5. The Pathway Decision and Return-to-Field

Every surviving surgery earns a disposition decision, made by the `ProgramCoordinator` and guarded by the cat-level concurrency check of §2.9: the request names the `pathway` and the `expected_cat_version`, and its checks run existence, then state, then the stale-version rejection (`ERR_STALE_VERSION`), then release-readiness. The decision point is a cat standing `POST_SURGERY` — and, by fall-through, a cat standing `ADOPTION_PIPELINE`, as described below. The decision itself is a mutation: it increments the cat's `version`.

No cat leaves the program unmarked. Any pathway decision requires `ear_tipped` and `vaccinated_rabies` both true on the cat; a decision attempted on an unmarked or unvaccinated cat is rejected with `ERR_NOT_RELEASE_READY` (HTTP 422).

Choosing `RETURN_TO_FIELD` at `POST_SURGERY` returns the cat to its territory: the cat moves from `POST_SURGERY` to `RETURNED`, its `pathway` is recorded as `RETURN_TO_FIELD`, and no `ACTIVE` foster placement may exist for the cat. Because `RETURNED` counts as sterilized, the colony's fraction and posture are recomputed. Choosing `ADOPTION` at `POST_SURGERY` is the adult branch — permitted only when `is_kitten` is false, since kittens never take this branch directly and instead enter the pipeline through the foster network of §3.6 — and moves the cat from `POST_SURGERY` to `ADOPTION_PIPELINE` with `pathway` recorded as `ADOPTION`; an adoption decision attempted on a kitten requests a transition that does not exist and is rejected with `ERR_INVALID_STATE`. Every pathway decision, whichever branch it takes, recomputes the colony's derived fields.

Adoption is not always permanent. A cat that fails to place can fall through: the same pathway decision capability, applied to a cat standing `ADOPTION_PIPELINE` with `pathway` set to `RETURN_TO_FIELD`, sends the cat back to `POST_SURGERY` and resets its `pathway` to null, re-opening the decision; a subsequent `RETURN_TO_FIELD` decision then applies from `POST_SURGERY` in the ordinary way.

Long-term confirmation closes the loop on returned cats. Once a field survey of the cat's colony — covered in §3.9 — exists whose `surveyed_on` falls on or after the moment the cat entered `RETURNED` and whose `eartipped_count` is at least 1, the `ProgramCoordinator` may confirm the cat long-term, moving it from `RETURNED` to `COLONY_STERILIZED`; without a qualifying survey the confirmation is rejected with `ERR_INVALID_STATE`. The colony's derivations are recomputed.

### 3.6. The Foster Network and the Adoption Pipeline

Kitten-season capacity lives in foster homes. A `ProgramCoordinator` registers a home with the `volunteer_name` and a `capacity_kittens` ceiling of at least 1; the home's `status` is `ACTIVE` or `PAUSED`, beginning `ACTIVE`, and its live load `current_kittens` counts the placements currently `ACTIVE` there. A home's placements, and a cat's placement history, are both listable with a `status` filter.

Placement is a coordinator action naming the `cat_id` and the `foster_home_id`, and its checks run in order: existence of the cat and the home; state, requiring the cat to stand `POST_SURGERY`; release-readiness — the same `ERR_NOT_RELEASE_READY` guard of §3.5, since no unmarked or unvaccinated kitten enters a home; the kitten rule — placement of a cat six months of age or older is rejected with `ERR_NOT_A_KITTEN` (HTTP 422); and home availability — a home that does not stand `ACTIVE`, or whose `current_kittens` has already reached its `capacity_kittens`, rejects the placement with `ERR_FOSTER_HOME_FULL` (HTTP 409). A successful placement moves the kitten from `POST_SURGERY` to `IN_FOSTER`, records its `pathway` as `ADOPTION`, increments the home's `current_kittens` by one, and stamps `placed_at` from the logical clock; the placement stands `ACTIVE`.

Two volunteer actions end a placement, and each requires the acting `FosterVolunteer` to operate their own home — the placement's home must match `X-User-ID`, else `ERR_OWNERSHIP_MISMATCH` — with the cat still `IN_FOSTER` and the placement still `ACTIVE`. Graduation sends a ready kitten onward: the placement ends as `ENDED_ADOPTION`, the cat moves from `IN_FOSTER` to `ADOPTION_PIPELINE`, and the home's `current_kittens` decrements by one. Returning to program is the foster loop: the placement ends as `ENDED_RETURNED`, the cat drops back from `IN_FOSTER` to `POST_SURGERY` with its `pathway` reset to null — the decision re-opened, so the kitten can be re-placed later — and the home's count decrements by one.

Adoption itself is finalized by the `ProgramCoordinator`: a cat standing `ADOPTION_PIPELINE` — whether it arrived as an adult via §3.5 or as a graduated kitten — becomes `ADOPTED`, leaves the colony's resident denominator, and triggers recomputation of the colony's fraction and posture.

### 3.7. Neighbor Complaints and Mediation

Complaints enter through the `AnimalControlOfficer`, who files against a colony with the neighbor's `complainant_name` and a `category` of `NOISE`, `ODOR`, `PROPERTY_DAMAGE`, `WILDLIFE_CONFLICT`, or `OVERPOPULATION`. The server stamps `filed_at` from the logical clock and derives `severity`: `HIGH` for `PROPERTY_DAMAGE` or `WILDLIFE_CONFLICT`, `STANDARD` for the remaining categories. A new complaint stands `OPEN`, and its arrival re-derives the colony's posture per §2.6 — an `OPEN` complaint holds an otherwise-`STABLE` colony at `WATCH`. A colony's complaints are listable with a `status` filter.

The working path runs `OPEN` to `IN_MEDIATION` to `RESOLVED`, both steps being officer actions; opening mediation re-derives the colony's posture, since the complaint has left the `OPEN` set, and so does resolution. Segregation of duties is deliberately not enforced: the officer who opened mediation may also resolve it. High-severity complaints support a second path: escalation moves an `OPEN` complaint whose `severity` is `HIGH` to `ESCALATED`, while escalating a `STANDARD` complaint requests a transition that does not exist and is rejected with `ERR_INVALID_STATE`. An escalated complaint requires coordinator sign-off to close — resolution moves it from `ESCALATED` to `RESOLVED` under the `ProgramCoordinator`, whereas an officer attempting to resolve an escalated complaint, or a coordinator attempting to resolve a merely-mediated one, requests a transition that does not exist for their role and is rejected with `ERR_INVALID_STATE`. Resolution by either path re-derives the colony's posture.

### 3.8. Voucher Issuance, Commitment, and Expiry

Vouchers are issued by the `ProgramCoordinator` to a named `caretaker_id`, with a `face_value_cents` strictly greater than zero and a `funding_source` of `MUNICIPAL_GRANT` or `DONATION_FUND`. The logical clock stamps the `issued_month`, and the monthly issuance cap of §2.8 is enforced against it — issuance beyond the caretaker's remaining headroom is rejected with `ERR_MONTHLY_CAP_EXCEEDED`, while an issuance that consumes the headroom exactly succeeds. A new voucher stands `ISSUED`, and a caretaker's voucher history is listable with a `status` filter.

Commitment happens at booking time per §3.3: the voucher must stand `ISSUED` — anything else, or a clinic that does not accept vouchers, yields `ERR_VOUCHER_NOT_USABLE` — and it must belong to the acting caretaker. From `COMMITTED`, the voucher resolves to `REDEEMED` on a surviving surgery or `VOIDED` on a mortality, per §3.4. Cancellation and the no-show sweep release it back from `COMMITTED` to `ISSUED`, and this issue-commit-release cycle may repeat any number of times.

Age kills idle vouchers. A coordinator-run expiry sweep moves every `ISSUED` voucher whose `issued_month` is at least three months before the current logical month to `EXPIRED`; committed, redeemed, and voided vouchers are untouched. If the sweep finds nothing old enough to expire, it is rejected with `ERR_NOTHING_TO_EXPIRE` (HTTP 422).

### 3.9. Population Surveys, Trend Reporting, and Colony Dissolution

Field monitoring is grounded in population surveys, recorded by the `ProgramCoordinator` or a `Caretaker`. A survey names the date the physical count took place in `surveyed_on`, the number of cats seen in `observed_count` (zero or more), and how many of them bore an ear tip in `eartipped_count`, with optional free-text `notes` defaulting to empty. Two consistency rules guard intake, each rejected with `ERR_SURVEY_INCONSISTENT` (HTTP 422): the ear-tipped count may not exceed the observed count, and the survey date may not lie in the future relative to the logical clock. Surveys are append-only — per §2.5 they carry no `updated_at` or `version` — and a colony's surveys are listable.

The population report applies the classification of §2.11 over the colony's full survey series, returning the trend label — `INSUFFICIENT_DATA`, `DECLINING`, `GROWING`, or `FLAT` — computed from the first and last observations in the pinned chronological order.

Dissolution closes a colony's lifecycle. A `ProgramCoordinator` may dissolve a colony only when every resident cat has reached a terminal state — `RETURNED`, `COLONY_STERILIZED`, `ADOPTED`, or `DECEASED`; while any resident cat remains in a non-terminal state the dissolution is rejected with `ERR_COLONY_NOT_DISSOLVABLE` (HTTP 409). A dissolved colony's `status` becomes `DISSOLVED`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — a caretaker, colony, cat, partner clinic, clinic day, appointment, surgery record, voucher, complaint, foster home, foster placement, or population survey — return `201 Created`. Operations that modify an existing resource or advance a lifecycle return `200 OK`. All program resources are mounted under `/tnr`; the clock control capability stands outside that prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | ProgramCoordinator |
| POST | `/tnr/caretakers` | Register a caretaker | ProgramCoordinator |
| GET | `/tnr/caretakers/{id}` | Fetch a caretaker | ProgramCoordinator, Caretaker, AnimalControlOfficer |
| GET | `/tnr/caretakers/{id}/vouchers` | List vouchers issued to a caretaker | ProgramCoordinator, Caretaker |
| POST | `/tnr/colonies` | Register a colony under a caretaker | ProgramCoordinator |
| GET | `/tnr/colonies/{id}` | Fetch a colony with its live derived fields | ProgramCoordinator, Caretaker, AnimalControlOfficer, ClinicStaff |
| GET | `/tnr/colonies` | List colonies with filters | ProgramCoordinator, Caretaker, AnimalControlOfficer |
| POST | `/tnr/colonies/{id}/dissolve` | Dissolve a colony whose resident cats are all terminal | ProgramCoordinator |
| POST | `/tnr/colonies/{id}/cats` | Add a cat to a colony | ProgramCoordinator, Caretaker |
| GET | `/tnr/colonies/{id}/cats` | List cats of a colony | ProgramCoordinator, Caretaker, AnimalControlOfficer, ClinicStaff, FosterVolunteer |
| GET | `/tnr/cats/{id}` | Fetch a cat | ProgramCoordinator, Caretaker, AnimalControlOfficer, ClinicStaff, FosterVolunteer |
| POST | `/tnr/cats/{id}/decide-pathway` | Decide the post-surgery disposition, including adoption fall-through (OCC-guarded on the cat) | ProgramCoordinator |
| POST | `/tnr/cats/{id}/finalize-adoption` | Mark an ADOPTION_PIPELINE cat as ADOPTED | ProgramCoordinator |
| POST | `/tnr/cats/{id}/confirm-long-term` | Confirm a RETURNED cat as COLONY_STERILIZED after a qualifying survey | ProgramCoordinator |
| POST | `/tnr/partner-clinics` | Onboard a partner clinic | ProgramCoordinator |
| GET | `/tnr/partner-clinics/{id}/clinic-days` | List clinic days hosted by a clinic | ProgramCoordinator, ClinicStaff, Caretaker |
| GET | `/tnr/partner-clinics/{id}` | Fetch a partner clinic | ProgramCoordinator, ClinicStaff |
| POST | `/tnr/clinic-days` | Schedule a clinic day and materialize its slots | ClinicStaff |
| GET | `/tnr/clinic-days/{id}` | Fetch a clinic day including booked_count | ProgramCoordinator, ClinicStaff, Caretaker |
| GET | `/tnr/clinic-days/{id}/slots` | List slots of a clinic day | ProgramCoordinator, ClinicStaff, Caretaker |
| GET | `/tnr/clinic-slots/{id}` | Fetch a clinic slot | ProgramCoordinator, ClinicStaff, Caretaker |
| POST | `/tnr/clinic-days/{id}/close` | Close a clinic day: no-show sweep and release of unused slots | ClinicStaff |
| POST | `/tnr/clinic-days/{id}/cancel` | Cancel an unbooked clinic day | ClinicStaff |
| POST | `/tnr/appointments` | Book a trapping appointment: reserve a slot and optionally commit a voucher (OCC-guarded on the clinic day) | Caretaker |
| GET | `/tnr/appointments/{id}` | Fetch an appointment | ProgramCoordinator, Caretaker, ClinicStaff |
| GET | `/tnr/cats/{id}/appointments` | List appointments for a cat | ProgramCoordinator, Caretaker, ClinicStaff |
| GET | `/tnr/clinic-slots/{id}/appointments` | List appointments booked against a slot | ProgramCoordinator, ClinicStaff |
| GET | `/tnr/vouchers/{id}/appointments` | List appointments that committed a voucher | ProgramCoordinator, Caretaker |
| POST | `/tnr/appointments/{id}/mark-trapped` | Caretaker confirms the cat is trapped | Caretaker |
| POST | `/tnr/appointments/{id}/check-in` | Clinic checks the trapped cat in | ClinicStaff |
| POST | `/tnr/appointments/{id}/cancel` | Caretaker cancels a scheduled appointment; slot and voucher released | Caretaker |
| POST | `/tnr/surgery-records` | Record a surgery outcome for a checked-in appointment | ClinicStaff |
| GET | `/tnr/appointments/{id}/surgery-records` | List surgery records of an appointment | ProgramCoordinator, ClinicStaff |
| POST | `/tnr/vouchers` | Issue a voucher to a caretaker under the monthly cap | ProgramCoordinator |
| GET | `/tnr/vouchers/{id}` | Fetch a voucher | ProgramCoordinator, Caretaker |
| POST | `/tnr/vouchers/expire-sweep` | Expire all ISSUED vouchers at least three months old | ProgramCoordinator |
| POST | `/tnr/colonies/{id}/complaints` | File a neighbor complaint against a colony | AnimalControlOfficer |
| GET | `/tnr/colonies/{id}/complaints` | List complaints against a colony | ProgramCoordinator, AnimalControlOfficer, Caretaker |
| POST | `/tnr/complaints/{id}/start-mediation` | Open mediation on a complaint | AnimalControlOfficer |
| POST | `/tnr/complaints/{id}/escalate` | Escalate a HIGH-severity complaint | AnimalControlOfficer |
| POST | `/tnr/complaints/{id}/resolve` | Resolve a complaint (IN_MEDIATION by officer; ESCALATED by coordinator) | AnimalControlOfficer, ProgramCoordinator |
| POST | `/tnr/foster-homes` | Register a foster home | ProgramCoordinator |
| GET | `/tnr/foster-homes/{id}` | Fetch a foster home including current_kittens | ProgramCoordinator, FosterVolunteer |
| GET | `/tnr/foster-homes/{id}/placements` | List placements at a foster home | ProgramCoordinator, FosterVolunteer |
| GET | `/tnr/cats/{id}/foster-placements` | List foster placements of a cat | ProgramCoordinator, FosterVolunteer, Caretaker |
| POST | `/tnr/foster-placements` | Place a post-surgery kitten into a foster home | ProgramCoordinator |
| POST | `/tnr/foster-placements/{id}/graduate` | Kitten leaves foster into the adoption pipeline | FosterVolunteer |
| POST | `/tnr/foster-placements/{id}/return-to-program` | Kitten returns from foster to the post-surgery decision point | FosterVolunteer |
| POST | `/tnr/colonies/{id}/population-surveys` | Record a field population survey | ProgramCoordinator, Caretaker |
| GET | `/tnr/colonies/{id}/population-surveys` | List population surveys of a colony | ProgramCoordinator, Caretaker, AnimalControlOfficer |
| GET | `/tnr/colonies/{id}/population-report` | Computed population trend report | ProgramCoordinator, AnimalControlOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_NOT_RELEASE_READY` | 422 Unprocessable Entity |
| `ERR_NOT_A_KITTEN` | 422 Unprocessable Entity |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_UNIQUENESS_VIOLATION` | 409 Conflict |
| `ERR_TEMPORAL_CONFLICT` | 422 Unprocessable Entity |
| `ERR_CLINIC_DAY_FULL` | 409 Conflict |
| `ERR_MONTHLY_CAP_EXCEEDED` | 402 Payment Required |
| `ERR_VOUCHER_NOT_USABLE` | 402 Payment Required |
| `ERR_FOSTER_HOME_FULL` | 409 Conflict |
| `ERR_SURVEY_INCONSISTENT` | 422 Unprocessable Entity |
| `ERR_DAY_HAS_BOOKINGS` | 409 Conflict |
| `ERR_NOTHING_TO_EXPIRE` | 422 Unprocessable Entity |
| `ERR_COLONY_NOT_DISSOLVABLE` | 409 Conflict |
