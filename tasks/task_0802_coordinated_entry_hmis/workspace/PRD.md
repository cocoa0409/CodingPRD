# Coordinated Entry & Homeless Services (HMIS) API — Product Requirements Document

## 1. Introduction

This document specifies the Coordinated Entry & Homeless Services API, the system of record for a community's homeless-response continuum. It carries a household from first contact through to a housing outcome: an intake worker registers a client, administers a VI-SPDAT vulnerability assessment, screens for diversion or a domestic-violence crisis, and — where shelter is warranted — reserves a bed against a finite, date-windowed pool. Clients who need more than emergency shelter enter a community prioritization pool, are ranked against their peers, and are matched to a housing navigator who carries them into a permanent-supportive-housing (PSH) enrollment. Throughout, the system honors release-of-information consent, de-duplicates records across agencies, and produces the aggregates a HUD-funded Continuum of Care must submit in its Annual Performance Report (APR).

The domain is unforgiving in two directions at once. Beds are a scarce, shared resource booked over half-open date windows: when one worker consumes the last bed, every other worker's view of availability is instantly stale, and a freed bed must be handed to the highest-priority waiting household without a human in the loop. At the same time, the data is sensitive: a client may not be shared, merged, or pooled without active consent, and revoking that consent must ripple through every downstream commitment. The requirements below define the entities, the state machines that govern their lifecycles, the calculations that rank and account for them, and the precise order in which every request is validated.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. If either header is missing, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles, spelled precisely as follows: `IntakeSpecialist`, `ShelterManager`, `HousingNavigator`, and `HMISAdmin`. An `IntakeSpecialist` runs intake, VI-SPDAT assessments, diversion screenings, and consent management. A `ShelterManager` manages shelters, beds, bed reservations, and waitlists. A `HousingNavigator` owns the prioritization pool, PSH referrals, and housing matches. An `HMISAdmin` performs de-duplication merges, navigator provisioning, APR reporting, and logical-clock control. The exact operation-to-role authorization is enumerated in the endpoint table of Section 4.

Three of the roles carry an opaque identity, and one is entity-backed. When `X-User-Role` is `IntakeSpecialist`, `ShelterManager`, or `HMISAdmin`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. When `X-User-Role` is `HousingNavigator`, the `X-User-ID` is the `id` of the acting `HousingNavigator`; ownership checks on any resource that references a `HousingNavigator` compare the resource's `navigator_id` foreign key to `X-User-ID`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Most resources carry a standard set of system-managed fields. Every resource has an `id`, a server-minted UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Resources that are mutable additionally carry an `updated_at` timestamp (refreshed on every change) and an integer `version` that starts at its initial value and increments by one on every mutation. `Client`, `Assessment`, `ROIConsent`, `DiversionScreening`, `Shelter`, `Bed`, `BedReservation`, `WaitlistEntry`, `PrioritizationEntry`, `HousingNavigator`, and `Referral` all carry the full set (`id`, `created_at`, `updated_at`, `version`). The `ExitRecord` is an append-only outcome record: it carries only `id` and `created_at`, and has neither `updated_at` nor `version`.

The system runs on a **logical clock** rather than wall-clock time. At startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any client sets it the clock never falls back to real time. An administrator advances the clock by supplying a `to_iso8601` instant; the response reports the new `current_utc`. The logical clock is the sole authority for every date- and time-dependent rule in this specification: consent effective and expiry dates, assessment and referral expiry windows, no-show eligibility, deferral dates, and the "current date" used when counting available beds. Several state transitions are described as happening "by the system" when the clock crosses a threshold; these lazy transitions are evaluated on the next read or write that touches the affected resource, not by any background process.

### 2.5. The Validation Pipeline and Its Fixed Priority Order

Every request is validated through an ordered pipeline. When more than one rule could fire, the earliest rule in the following order wins, and its error is the one returned — a later, more specific failure must never mask an earlier one.

1. **Authentication.** Both `X-User-Role` and `X-User-ID` headers must be present, or the request fails with `ERR_UNAUTHENTICATED` (401). This applies to every endpoint.
2. **Authorization.** The declared role must be permitted for the operation per Section 4, or the request fails with `ERR_FORBIDDEN` (403). This applies to every endpoint.
3. **Existence.** Every referenced resource must exist, checked left to right — first the path identifier, then each foreign key carried in the body. The first identifier that resolves to nothing yields `ERR_NOT_FOUND` (404). This applies to every endpoint.
4. **Well-formedness.** The request must be well-formed: all required fields present, all enums and types valid, and for any reservation or waitlist window the `entry_date` must be strictly before the `expected_exit_date`. A violation yields `ERR_INVALID_REQUEST` (400). This applies to every endpoint.
5. **State.** For any state-transition endpoint, the target resource must be in a state from which the transition is legal, or the request fails with `ERR_INVALID_STATE` (409). This applies to all state-transition endpoints.
6. **Optimistic concurrency.** On bed-reservation creation, the supplied `expected_shelter_version` must equal the shelter's current `version`, or the request fails with `ERR_STALE_VERSION` (412). This applies only to reservation creation.
7. **Assessment prerequisite.** On referral creation, the client must have at least one `COMPLETED` `Assessment`, or the request fails with `ERR_ASSESSMENT_REQUIRED` (409). This applies only to referral creation.
8. **Consent prerequisite.** Bed check-in and client merge require an `ACTIVE` `ROIConsent` for the subject client (the duplicate, on a merge), or the request fails with `ERR_CONSENT_REQUIRED` (409). This applies to reservation check-in and to client merge.
9. **Merge validity.** On a merge, the duplicate and the master must be different clients and the duplicate must not already be `MERGED`, or the request fails with `ERR_MERGE_INVALID` (409). This applies only to client merge.
10. **Client double-booking.** On reservation creation, the same client may not hold two reservations occupying the same night, or the request fails with `ERR_CLIENT_DOUBLE_BOOKED` (409). This applies only to reservation creation.
11. **Caseload capacity.** On referral acceptance, the navigator's `current_caseload` must be below their `max_caseload`, or the request fails with `ERR_CASELOAD_FULL` (409). This applies only to referral acceptance.
12. **Bed-label uniqueness.** On bed creation, the `label` must be unique within its shelter, or the request fails with `ERR_DUPLICATE_BED_LABEL` (409). This applies only to bed creation.
13. **Waitlist uniqueness.** On waitlist creation, the client must not already have a `WAITING` entry at that shelter, or the request fails with `ERR_DUPLICATE_WAITLIST` (409). This applies only to waitlist creation.
14. **Capacity availability.** On reservation creation, an assignable bed must exist for the requested window, or the request fails with `ERR_SHELTER_AT_CAPACITY` (409). This applies only to reservation creation.
15. **Pool eligibility.** On prioritization-pool placement, the client must hold an `ACTIVE` `ROIConsent` and must not already have a non-terminal pool entry, or the request fails with `ERR_POOL_INELIGIBLE` (409). This applies only to pool placement.
16. **Exit idempotency.** On exit-record creation, the referenced enrollment must not already be exited, or the request fails with `ERR_ALREADY_EXITED` (409). This applies only to exit-record creation.

Note that on reservation creation four business rules stack in this exact order after well-formedness: the stale-version check (rule 6), then the client double-booking check (rule 10), then the capacity-availability check (rule 14). A stale shelter view is therefore reported before a double-booking conflict, and both are reported before the pool is found to be full.

### 2.6. Optimistic Concurrency on the Shared Bed Pool

A shelter's bed pool is a shared resource that multiple `ShelterManager` operators book concurrently, so reservation creation is guarded by optimistic concurrency control on the shelter. Creating a reservation requires the client to supply `expected_shelter_version`, carrying the shelter `version` they last observed (a `Shelter` is fetched with its current `version` for exactly this purpose). If another writer has advanced the shelter's `version` since then — by booking, cancelling, checking in or out, or taking a bed offline or online, all of which legitimately mutate the shared pool — then the caller's view of availability is stale and the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a writer from occupying the last non-overlapping bed that another writer has already consumed. `expected_shelter_version` is a required input on reservation creation and appears on no other endpoint; no other write takes a version field.

### 2.7. Capacity Accounting, Half-Open Windows, and Turnover

Bed occupancy is modeled with **half-open date intervals**. A reservation with entry date and expected exit date occupies every night from the entry date up to, but not including, the exit date — written `[entry_date, expected_exit_date)`. Two reservations conflict on a bed only when their half-open windows genuinely overlap; adjacency does not conflict, so a reservation whose exit date equals another's entry date may share the same bed because no night is double-occupied.

A shelter exposes two computed counts. Its `total_beds` is the number of `Bed` rows under the shelter across all statuses. Its `available_beds` is the number of `ACTIVE` beds that have no `RESERVED` or `CHECKED_IN` reservation covering the current logical-clock date. Both are recomputed on any capacity change — reservation create, cancel, check-out, or no-show, and bed offline or online.

Whenever capacity frees up, the system must resolve the freeing event and any resulting waitlist promotion in one pinned order, because a promotion itself creates a reservation that re-consumes capacity. The order is: first apply the triggering mutation (terminalize the freed reservation, or flip the bed's status); then recompute the shelter's free windows from the reservations that remain live; then run waitlist promotion against that freshly recomputed picture, never against a pre-mutation snapshot; and finally, if a promotion mints a new reservation, apply the first two steps again for that new reservation. This ordering guarantees the promoted household is placed against real, current availability.

### 2.8. Scoring, Precision, and Rounding

All vulnerability scores, priority and rank scores, caseload counts, bed-night counts, and bed counts are integers. Score thresholds are evaluated with inclusive boundaries wherever the rule says "at least."

The APR report is the only place fractional values appear, and its rounding is fixed. The positive-exit rate is reported to one decimal place and the average length of stay to two decimal places, both using round-half-up. Every APR figure is computed by summing whole counts first and dividing exactly once at the end — never by rounding a per-record value and then averaging. When a denominator would be zero, the quotient is defined as `0.0` rather than an error.

### 2.9. Consent, De-duplication, and Referential Consistency

Release-of-information consent gates the most sensitive operations. A client may not be checked into a bed, merged as a duplicate, or placed into the prioritization pool without an `ACTIVE` `ROIConsent`. When consent is later revoked or a client is merged away, the system cascades those withdrawals downstream automatically, terminating pool entries and cancelling occupying reservations as described in the workflows of Section 3. Every automatic transition the server performs on a resource is a real mutation of that resource: it refreshes the resource's `updated_at` and increments its `version`, exactly as an explicit client request would. In particular, each capacity change on a shelter increments `Shelter.version`, which is what makes a concurrent reservation writer's `expected_shelter_version` go stale.

When an endpoint path names a resource by `id`, that identifier is validated before any foreign key in the body, and the first missing identifier — path before body, in left-to-right order — produces `ERR_NOT_FOUND`.

## 3. Business Logic & Workflows

### 3.1. Intake, Assessment, and the VI-SPDAT Vulnerability Score

A household enters the system when an `IntakeSpecialist` (or an `HMISAdmin`) registers a **Client**. Intake captures the client's `full_name`, `dob` (date of birth as `YYYY-MM-DD`), and optionally `ssn_last4` (the last four digits of the SSN, four digits or null, used only as a de-duplication candidacy signal). Three household attributes may be supplied and otherwise take defaults: `household_size` defaults to 1 and must be at least 1; `months_homeless`, the self-reported cumulative months homeless, defaults to 0 and must be at least 0; and `chronic_homeless`, the HUD chronic-homelessness flag, defaults to false. A newly registered client enters in `INTAKE` status. As the client progresses they move through `ACTIVE`, and ultimately to `HOUSED`, `INACTIVE`, or the terminal `MERGED`. A client's `master_client_id` is null until they are merged into a surviving master, at which point it holds that master's `id`. Two derived attributes, `vulnerability_score` and `acuity_tier`, are null until the client is first assessed.

Assessment uses the VI-SPDAT tool. An `IntakeSpecialist` opens an **Assessment** against a client by supplying the `client_id`, an optional `tool` (which defaults to `VI_SPDAT`, the only permitted value), the `self_report_points` (the sum of self-reported VI-SPDAT points at intake, from 0 to 17 inclusive), and an optional `verification_delta` (points added or removed once documents are verified, from -5 to 5 inclusive, defaulting to 0). A new assessment is `DRAFT`. While it is `DRAFT`, its `provisional_score` is simply the `self_report_points`, ignoring the delta. Completing the assessment computes the `verified_score` as the `self_report_points` plus the `verification_delta`, clamped to the range 0 through 17 (values below 0 become 0, values above 17 become 17). The assessment's `recommended_track` is derived from that verified score's tier on completion.

Completion is the pivot of intake. When an `IntakeSpecialist` completes a `DRAFT` assessment, the assessment moves `DRAFT → COMPLETED`, the `verified_score` and `recommended_track` are computed, and the subject client's `vulnerability_score` is set to that verified score with `acuity_tier` recomputed. A client's `vulnerability_score` always reflects the `verified_score` of the client's latest `COMPLETED` assessment, where "latest" means most recent by `created_at` in descending order (the resource `id` is never used as a tie-break). If completing this assessment is the client's first completed assessment while the client is still in `INTAKE`, the client transitions `INTAKE → ACTIVE` as part of the same operation. Completing an assessment that is not `DRAFT` is rejected with `ERR_INVALID_STATE`.

The **acuity tier** is a pure function of the vulnerability score, recomputed whenever that score changes. If the score is null, the tier is null. If the score is at least 8, the tier is `HIGH`, which recommends the `PSH` track. Otherwise, if the score is at least 4, the tier is `MODERATE`, which recommends the `RRH` track. Otherwise the tier is `LOW`, which recommends the `PREVENTION` track. The `recommended_track` stored on the assessment follows the same mapping: `HIGH` to `PSH`, `MODERATE` to `RRH`, and `LOW` to `PREVENTION`.

A draft assessment does not live forever. Once the logical clock reaches 90 days past the assessment's `created_at` while it is still `DRAFT`, the assessment is treated as `EXPIRED`; this lazy transition is applied the next time the assessment is read or written. An `HMISAdmin` may also deactivate a client: a client in `ACTIVE` moves to `INACTIVE`, provided the client holds no `RESERVED` or `CHECKED_IN` reservation; a client in any other state is rejected with `ERR_INVALID_STATE`.

### 3.2. Consent and Data Sharing

An `IntakeSpecialist` records a **release-of-information consent** for a client by supplying the `client_id`, the sharing `scope` (either `SHARE_ALL` or `SHARE_LIMITED`), an `effective_date` (the inclusive date on which consent begins, `YYYY-MM-DD`), and an `expiry_date` (the exclusive date on which it lapses). A new consent is `PENDING`. Activating a `PENDING` consent moves it to `ACTIVE`, but only once the logical-clock date is on or after the `effective_date`; activating before the effective date, or activating a consent that is not `PENDING`, is rejected with `ERR_INVALID_STATE`. Activation is what unlocks de-duplication and prioritization-pool placement for the client.

Consent can end in two ways. An `IntakeSpecialist` may revoke an `ACTIVE` consent, moving it `ACTIVE → REVOKED`; revoking a consent that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`. Revocation cascades: the client's `ACTIVE` `PrioritizationEntry`, if any, is driven to `REMOVED`, because the community may no longer act on a client who has withdrawn consent. Separately, once the logical-clock date reaches the `expiry_date`, an `ACTIVE` consent is treated as `EXPIRED`; this lazy transition is applied on the next read or write of the consent. Because check-in, merge, and pool placement all require an `ACTIVE` consent at the moment they run, a lapsed or revoked consent silently closes those doors.

### 3.3. Diversion and Crisis Triage

Before committing a household to shelter, an `IntakeSpecialist` may run a **diversion screening**. Creating one requires the `client_id` and the `has_safe_alternative` flag (whether the client has a safe temporary alternative to shelter), plus an optional `is_fleeing_dv` flag (fleeing domestic violence, a crisis-triage signal, defaulting to false). A new screening is `OPEN`. Resolving an `OPEN` screening moves it `OPEN → RESOLVED` and derives its `outcome` by a strict priority: if the client is fleeing domestic violence, the outcome is `PROCEED_TO_SHELTER` regardless of any alternative; otherwise, if the client has a safe alternative, the outcome is `DIVERTED`; otherwise the outcome is `PROCEED_TO_PRIORITIZATION`. Resolving a screening that is not `OPEN` is rejected with `ERR_INVALID_STATE`.

### 3.4. Shelters, Beds, and Bed Reservations

A `ShelterManager` (or `HMISAdmin`) creates a **Shelter** with a `name` and a `project_type` — either `ES` for Emergency Shelter or `TH` for Transitional Housing. A shelter begins with `total_beds` and `available_beds` both at zero. A `ShelterManager` then adds **Beds** by supplying the owning `shelter_id` and a human `label`; the label must be unique within its shelter, and a collision is rejected with `ERR_DUPLICATE_BED_LABEL`. A new bed is `ACTIVE`, and adding a bed recomputes the shelter's `total_beds` and `available_beds` and increments `Shelter.version`. A bed's `status` reflects physical usability rather than occupancy, and its `current_reservation_id` names the reservation checked into it right now, null when unoccupied. A `ShelterManager` may take an `ACTIVE` bed offline — `ACTIVE → OFFLINE` — only when it has no active occupant (its `current_reservation_id` is null); this increments `Shelter.version` and recomputes `available_beds`. Bringing an `OFFLINE` bed back — `OFFLINE → ACTIVE` — likewise increments `Shelter.version`, recomputes `available_beds`, and additionally triggers a waitlist-promotion evaluation, since new capacity has appeared. An offline attempt on a bed that is not `ACTIVE`, or an online attempt on a bed that is not `OFFLINE`, is rejected with `ERR_INVALID_STATE`.

Reserving capacity is the core operation. A `ShelterManager` creates a **BedReservation** by supplying the `client_id`, the target `shelter_id`, the `entry_date` (inclusive start, `YYYY-MM-DD`), the `expected_exit_date` (exclusive end), and the `expected_shelter_version` for the concurrency check described in Section 2.6. The client does not choose a bed; the server assigns one. The reservation's `bed_id` is filled by the **bed-assignment selector**, which considers the beds under the requested shelter whose `status` is `ACTIVE` and which have no `RESERVED` or `CHECKED_IN` reservation whose window overlaps the requested `[entry_date, expected_exit_date)` — remembering that adjacency, where one window's exit equals another's entry, is not an overlap. Among the qualifying beds it selects the one created earliest, breaking ties by `label` in ascending order (the resource `id` is never used as a tie-break); that bed's `id` becomes the reservation's `bed_id`. If no bed qualifies, the request is rejected with `ERR_SHELTER_AT_CAPACITY`. A successful reservation is `RESERVED`, increments `Shelter.version`, and recomputes `available_beds`. The reservation also records an `exit_date`, which is null until the client actually checks out.

A single client may not double-book. On reservation creation, if the same client already holds a reservation occupying any of the same nights, the request is rejected with `ERR_CLIENT_DOUBLE_BOOKED`. Unlike bed-to-bed conflict, the client double-booking check treats the interval as **inclusive of the turnover day**: if one stay's exit date equals another stay's entry date, that shared turnover day is a conflict for the same client even though it would have been permissible adjacency for two different clients on one bed.

The reservation lifecycle runs through several `ShelterManager` actions. Checking a client in advances a `RESERVED` reservation to `CHECKED_IN`, but only if the reserving client holds an `ACTIVE` `ROIConsent`; without it the check-in is rejected with `ERR_CONSENT_REQUIRED`. On check-in the assigned bed's `current_reservation_id` is set to this reservation, marking the bed occupied. Checking a client out advances a `CHECKED_IN` reservation to `CHECKED_OUT`: the reservation's `exit_date` is set to the current logical-clock date, the bed's `current_reservation_id` is cleared so the bed is free, `Shelter.version` is incremented, `available_beds` is recomputed, and a waitlist promotion is evaluated against the freed capacity. Cancelling a `RESERVED` reservation moves it to `CANCELLED`, freeing its window on the assigned bed, incrementing `Shelter.version`, recomputing `available_beds`, and evaluating waitlist promotion. Marking a `RESERVED` reservation as a no-show moves it to `NO_SHOW`, but only once the logical-clock date is strictly past the `entry_date`; it likewise frees the window, increments `Shelter.version`, recomputes `available_beds`, and evaluates promotion. A no-show attempt before the entry date has passed, or any of these transitions from a state that does not allow them, is rejected with `ERR_INVALID_STATE`. A reservation may also be driven from `CHECKED_IN` to `CANCELLED` by the system as a consequence of a client merge (see Section 3.7); that system cancellation clears the bed's `current_reservation_id`, increments `Shelter.version`, recomputes `available_beds`, and evaluates waitlist promotion, exactly as an operator cancellation would.

### 3.5. The Waitlist and Automatic Promotion

When a shelter is full, a `ShelterManager` adds a client to its **waitlist** by supplying the `shelter_id`, the `client_id`, and the requested `entry_date` and `expected_exit_date`. A client may hold only one active waiting entry per shelter; a second `WAITING` entry at the same shelter is rejected with `ERR_DUPLICATE_WAITLIST`. A new entry is `WAITING`, and its `priority_score` is snapshotted at creation from the client's community ranking (the same formula that ranks the prioritization pool, described in Section 3.6, evaluated against the waiting client at that moment). A `ShelterManager` may cancel a `WAITING` entry, moving it `WAITING → CANCELLED`; cancelling an entry that is not `WAITING` is rejected with `ERR_INVALID_STATE`.

Promotion is automatic and happens whenever capacity frees at a shelter — a check-out, a cancellation, a no-show, a merge-driven cancellation, or a bed coming back online. The **promotion selector** gathers the shelter's `WAITING` entries for which an `ACTIVE` bed exists with no `RESERVED` or `CHECKED_IN` reservation overlapping that entry's requested `[entry_date, expected_exit_date)` window. Among that candidate set it chooses the entry with the highest `priority_score`, breaking ties by `created_at` in ascending order (never by `id`). The chosen entry moves `WAITING → PROMOTED`, and a fresh `RESERVED` reservation is minted for it with a server-assigned bed; the entry's `promoted_reservation_id` records that new reservation's `id`. If no candidate qualifies — no waiting entry can be served by a currently free, non-overlapping bed — no promotion occurs and the freed capacity simply remains available. Promotion always evaluates against the recomputed post-mutation availability, following the pinned order of Section 2.7, so a promoted reservation that re-consumes capacity is accounted for before any further promotion is considered.

### 3.6. The Prioritization Pool, Navigators, and PSH Referrals

Clients who need coordinated placement enter the **community prioritization pool**. A `HousingNavigator` (or `HMISAdmin`) places a client into the pool by supplying the `client_id`. Placement requires the client to hold an `ACTIVE` `ROIConsent` and to have no existing non-terminal pool entry; either failing condition is rejected with `ERR_POOL_INELIGIBLE`. A new **PrioritizationEntry** is `ACTIVE` and receives a computed `rank_score`. Its `deferred_until` is null unless the entry is deferred, and its `matched_referral_id` is null until it is matched.

The `rank_score` combines four contributions computed against the client's attributes at compute time. The first is a tier weight from the client's `acuity_tier`: 1000 for `HIGH`, 500 for `MODERATE`, 100 for `LOW`, and 0 for an unscored client whose tier is null. The second is a chronic bonus of 300 if the client's `chronic_homeless` flag is set, and 0 otherwise. The third is a time-homeless contribution: if the client's `months_homeless` is at least 12, it contributes 200; otherwise, if `months_homeless` is at least 6, it contributes 100; otherwise it contributes the `months_homeless` multiplied by 10. The fourth is a household factor equal to the smaller of the client's `household_size` and 5, multiplied by 20 (so household size is capped at 5 for this purpose). The `rank_score` is the sum of these four contributions. This same computation produces the waitlist `priority_score` snapshot in Section 3.5.

A `HousingNavigator` may defer an `ACTIVE` pool entry until a later date by supplying `deferred_until`; the entry moves `ACTIVE → DEFERRED` and is excluded from matching until the logical clock reaches that date. Reactivating a `DEFERRED` entry moves it `DEFERRED → ACTIVE`, clears `deferred_until` back to null, and recomputes the `rank_score` against the client's current attributes. Deferring an entry that is not `ACTIVE`, or reactivating one that is not `DEFERRED`, is rejected with `ERR_INVALID_STATE`. An `ACTIVE` pool entry may also be driven to the terminal `REMOVED` state by the system as a cascade from consent revocation or a client merge.

Housing navigation is staffed by **HousingNavigators**, provisioned by an `HMISAdmin` with a `name` and a `max_caseload` (the maximum number of simultaneously accepted referrals, at least 1). A navigator's `current_caseload` is the live count of that navigator's referrals in `ACCEPTED` status. It begins at zero, rises by one when a referral is accepted, and falls by one both when an accepted referral is declined and when an accepted referral is enrolled — so a forward accept paired with its compensating decline leaves the caseload where it started.

A `HousingNavigator` creates a **Referral** to match a pool entry to a PSH opening by supplying the `client_id`, the `prioritization_entry_id` being matched, the assigned `navigator_id`, and the target `psh_project_name`. Creating a referral requires the pool entry to be `ACTIVE` and the client to have a `COMPLETED` `Assessment`; a client with no completed assessment is rejected with `ERR_ASSESSMENT_REQUIRED`. On success the referral is `PENDING` and its pool entry moves `ACTIVE → MATCHED`, recording the new referral's `id` in the entry's `matched_referral_id`. The referral lifecycle then branches:

- **Accept.** A `PENDING` referral moves to `ACCEPTED` only if the navigator's `current_caseload` is below their `max_caseload`; otherwise the request is rejected with `ERR_CASELOAD_FULL`. Acceptance increases the navigator's `current_caseload` by one.
- **Decline from `PENDING`.** Declining a `PENDING` referral moves it `PENDING → DECLINED` and re-queues the pool entry, driving `MATCHED → ACTIVE` (its `matched_referral_id` cleared to null and its `rank_score` recomputed as it returns to the pool). Because the referral was never accepted, the caseload is unchanged.
- **Decline from `ACCEPTED`.** Declining an `ACCEPTED` referral moves it `ACCEPTED → DECLINED`, decrements the navigator's `current_caseload` by one to compensate for the earlier acceptance, and re-queues the pool entry `MATCHED → ACTIVE` (clearing `matched_referral_id` and recomputing `rank_score`).
- **Enroll.** Enrolling an `ACCEPTED` referral moves it `ACCEPTED → ENROLLED`. This cascades: the pool entry moves `MATCHED → HOUSED`, the client moves `ACTIVE → HOUSED` and leaves the pool, and the navigator's `current_caseload` decrements by one as the referral leaves `ACCEPTED` for `ENROLLED`.
- **Expiry.** A referral left `PENDING` until the logical clock reaches 14 days past its `created_at` is treated as `EXPIRED`, evaluated lazily on the next read or write; expiry re-queues its pool entry `MATCHED → ACTIVE`.

Any of these transitions attempted from a state that does not permit it is rejected with `ERR_INVALID_STATE`. The re-queue path — a matched entry returning to `ACTIVE` on decline or expiry and later being matched again — is the pool's intended cycle, allowing a client to be matched, released, and rematched without leaving the community's queue.

### 3.7. De-duplication and Client Merges

Because a household may be registered by more than one agency, an `HMISAdmin` de-duplicates records by merging a duplicate client into a surviving master. The merge targets the master client by path `id` and names the duplicate through `duplicate_client_id` in the body. The duplicate and master must be different clients, and the duplicate must not already be `MERGED`; a self-merge or an already-merged duplicate is rejected with `ERR_MERGE_INVALID`. The duplicate must also hold an `ACTIVE` `ROIConsent` — de-duplication is a data-sharing act and requires consent — or the merge is rejected with `ERR_CONSENT_REQUIRED`. The duplicate must be in `INTAKE` or `ACTIVE`; a duplicate in any other state cannot be merged.

On a successful merge the duplicate moves to the terminal `MERGED` state and its `master_client_id` is set to the master's `id`. When the duplicate was `ACTIVE`, the merge additionally cascades to unwind the duplicate's live commitments: any `RESERVED` or `CHECKED_IN` reservation held by the duplicate is cancelled — which in turn frees the bed and triggers waitlist promotion following the pinned capacity order — and the duplicate's `ACTIVE` `PrioritizationEntry`, if any, is driven to `REMOVED`. When the duplicate was still in `INTAKE`, there are no such downstream commitments, so the merge only records the `master_client_id` without further cascade. Clients that were merged away remain discoverable: listing clients filtered by `master_client_id` returns the duplicate children pointing at a given master.

### 3.8. Exits, Outcomes, and HUD APR Reporting

An enrollment ends with an **ExitRecord**, created by a `ShelterManager`, `HousingNavigator`, or `HMISAdmin`. The record names the exiting `client_id`, a `destination`, and exactly one enrollment reference: a `reservation_id` for a shelter exit or a `referral_id` for a PSH exit (the other is null). The referenced enrollment must not already have been exited, or the request is rejected with `ERR_ALREADY_EXITED`.

The record's `outcome` is derived from the `destination`. An exit to `PERMANENT_HOUSING` or `RRH` is `POSITIVE`. An exit to `TEMP_FAMILY` or `INSTITUTION` is `NEUTRAL`. An exit to `EMERGENCY_SHELTER`, `STREET`, or `UNKNOWN` is `NEGATIVE`. The record also carries `bed_nights`, the length of stay for shelter exits. For a shelter exit, `bed_nights` is the number of nights between the reservation's `entry_date` and its `exit_date` counting the entry day but excluding the exit day (the half-open bed-night count used for HUD point-in-time counting). A parallel enrollment-duration measure, which includes both endpoints and therefore equals the bed-night count plus one, exists for case-management duration reporting but is not what `bed_nights` stores. For a PSH exit, where `reservation_id` is null, `bed_nights` is 0.

The **APR report**, available to an `HMISAdmin`, aggregates outcomes for HUD's Annual Performance Report. It accepts an optional `shelter_id` to scope to a single shelter (matching exit records through their reservation's shelter) and an optional `as_of_date`. Its scope is the set of exit records created strictly before the `as_of_date`. From that scope the report computes `total_exited` as the count of records in scope and `positive_exit_rate` as the count of `POSITIVE` exits divided by `total_exited`, multiplied by 100 and rounded to one decimal place; the division is performed once over summed counts. It computes `avg_length_of_stay` as the sum of `bed_nights` over the scoped records divided by `total_exited`, rounded to two decimal places, again summing first and dividing once rather than averaging per-record rounded values. When the scope is empty, both `positive_exit_rate` and `avg_length_of_stay` are `0.0`. Finally, `total_enrolled` counts the currently open enrollments: reservations in `RESERVED` or `CHECKED_IN` plus referrals in `ACCEPTED` or `ENROLLED`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that fetch, list, or modify an existing resource — including every state-transition action and the merge and deactivate operations — return `200 OK`. All request bodies and response bodies follow the envelope of Section 2.2; the request fields, side effects, and computed outputs of each endpoint are specified in the narrative of Section 3, not in this table.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clients` | Create a client (intake) | IntakeSpecialist, HMISAdmin |
| GET | `/clients/{id}` | Get a client | IntakeSpecialist, ShelterManager, HousingNavigator, HMISAdmin |
| GET | `/clients` | List/search clients | IntakeSpecialist, ShelterManager, HousingNavigator, HMISAdmin |
| POST | `/clients/{id}/merge` | Merge a duplicate client into this master | HMISAdmin |
| POST | `/clients/{id}/deactivate` | Deactivate a client | HMISAdmin |
| POST | `/assessments` | Create a VI-SPDAT assessment (DRAFT) | IntakeSpecialist |
| GET | `/assessments/{id}` | Get an assessment | IntakeSpecialist, HousingNavigator, HMISAdmin |
| GET | `/assessments` | List assessments | IntakeSpecialist, HousingNavigator, HMISAdmin |
| POST | `/assessments/{id}/complete` | Complete an assessment; compute verified score | IntakeSpecialist |
| POST | `/consents` | Record an ROI consent (PENDING) | IntakeSpecialist |
| GET | `/consents/{id}` | Get a consent | IntakeSpecialist, HMISAdmin |
| GET | `/consents` | List consents | IntakeSpecialist, HMISAdmin |
| POST | `/consents/{id}/activate` | Activate a consent | IntakeSpecialist |
| POST | `/consents/{id}/revoke` | Revoke a consent | IntakeSpecialist |
| POST | `/screenings` | Create a diversion/crisis-triage screening (OPEN) | IntakeSpecialist |
| GET | `/screenings/{id}` | Get a screening | IntakeSpecialist, HMISAdmin |
| GET | `/screenings` | List screenings | IntakeSpecialist, HMISAdmin |
| POST | `/screenings/{id}/resolve` | Resolve a screening; derive outcome | IntakeSpecialist |
| POST | `/shelters` | Create a shelter | ShelterManager, HMISAdmin |
| GET | `/shelters/{id}` | Get a shelter (includes version for OCC) | IntakeSpecialist, ShelterManager, HousingNavigator, HMISAdmin |
| GET | `/shelters` | List shelters | IntakeSpecialist, ShelterManager, HousingNavigator, HMISAdmin |
| POST | `/beds` | Add a bed to a shelter | ShelterManager |
| GET | `/beds/{id}` | Get a bed | ShelterManager, HMISAdmin |
| GET | `/beds` | List beds | ShelterManager, HMISAdmin |
| POST | `/beds/{id}/offline` | Take an unoccupied bed offline | ShelterManager |
| POST | `/beds/{id}/online` | Return a bed online | ShelterManager |
| POST | `/bed-reservations` | Reserve capacity; server assigns a bed (OCC on shelter) | ShelterManager |
| GET | `/bed-reservations/{id}` | Get a reservation | ShelterManager, HMISAdmin |
| GET | `/bed-reservations` | List reservations | ShelterManager, HMISAdmin |
| POST | `/bed-reservations/{id}/check-in` | Check a client into their reserved bed | ShelterManager |
| POST | `/bed-reservations/{id}/check-out` | Check a client out; free bed; promote waitlist | ShelterManager |
| POST | `/bed-reservations/{id}/cancel` | Cancel a reservation before check-in | ShelterManager |
| POST | `/bed-reservations/{id}/no-show` | Mark a reservation as no-show | ShelterManager |
| POST | `/waitlist-entries` | Add a client to a shelter waitlist | ShelterManager |
| GET | `/waitlist-entries/{id}` | Get a waitlist entry | ShelterManager, HMISAdmin |
| GET | `/waitlist-entries` | List waitlist entries | ShelterManager, HMISAdmin |
| POST | `/waitlist-entries/{id}/cancel` | Cancel a waitlist entry | ShelterManager |
| POST | `/prioritization-entries` | Place a client into the prioritization pool | HousingNavigator, HMISAdmin |
| GET | `/prioritization-entries/{id}` | Get a prioritization entry | HousingNavigator, HMISAdmin |
| GET | `/prioritization-entries` | List pool entries | HousingNavigator, HMISAdmin |
| POST | `/prioritization-entries/{id}/defer` | Defer an entry until a date | HousingNavigator |
| POST | `/prioritization-entries/{id}/reactivate` | Reactivate a deferred entry | HousingNavigator |
| POST | `/housing-navigators` | Create a housing navigator | HMISAdmin |
| GET | `/housing-navigators/{id}` | Get a navigator | HousingNavigator, HMISAdmin |
| GET | `/housing-navigators` | List navigators | HousingNavigator, HMISAdmin |
| POST | `/referrals` | Create a PSH referral matching a pool entry to a navigator | HousingNavigator |
| GET | `/referrals/{id}` | Get a referral | HousingNavigator, HMISAdmin |
| GET | `/referrals` | List referrals | HousingNavigator, HMISAdmin |
| POST | `/referrals/{id}/accept` | Navigator accepts the referral | HousingNavigator |
| POST | `/referrals/{id}/decline` | Navigator declines the referral (re-queue pool entry) | HousingNavigator |
| POST | `/referrals/{id}/enroll` | Enroll the client into PSH | HousingNavigator |
| POST | `/exit-records` | Record an exit & outcome for a shelter or PSH enrollment | ShelterManager, HousingNavigator, HMISAdmin |
| GET | `/exit-records/{id}` | Get an exit record | ShelterManager, HousingNavigator, HMISAdmin |
| GET | `/exit-records` | List exit records | ShelterManager, HousingNavigator, HMISAdmin |
| GET | `/reports/apr` | HUD HMIS Annual Performance Report aggregates | HMISAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | HMISAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_ASSESSMENT_REQUIRED` | 409 |
| `ERR_CONSENT_REQUIRED` | 409 |
| `ERR_MERGE_INVALID` | 409 |
| `ERR_CLIENT_DOUBLE_BOOKED` | 409 |
| `ERR_CASELOAD_FULL` | 409 |
| `ERR_DUPLICATE_BED_LABEL` | 409 |
| `ERR_DUPLICATE_WAITLIST` | 409 |
| `ERR_SHELTER_AT_CAPACITY` | 409 |
| `ERR_POOL_INELIGIBLE` | 409 |
| `ERR_ALREADY_EXITED` | 409 |
