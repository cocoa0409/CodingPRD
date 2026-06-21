# Animal Shelter & Adoption API — Product Requirements Document

## 1. Introduction

This document specifies the Animal Shelter & Adoption API, the system of record for a municipal-style shelter that takes animals into custody, cares for them, and routes them toward one of several outcomes: adoption, return to a prior owner, foster placement, or — as a last resort and under strict dual control — humane euthanasia. The API is built around an auditable, compliance-first posture: every meaningful event (an intake, a medical exam, a kennel assignment, a fee collection, a euthanasia approval) is a recorded, role-gated transition, and the financial and occupancy ledgers it maintains must remain reconcilable at all times.

The operational reality the API models is one of competing constraints. A stray cannot be adopted out or euthanized until its mandatory stray-hold period has elapsed, giving a prior owner the chance to reclaim it. A kennel has finite capacity and must never be double-booked. A foster home can host only so many animals at once and needs a recovery gap between placements. An animal's medical readiness evolves on a track entirely separate from its custody status, so a perfectly healthy animal may still be ineligible for adoption because it is mid-hold, and a hold-elapsed animal may still be ineligible because it has not been medically cleared. The system keeps these axes independent yet jointly enforced.

Because the shelter answers to auditors and to the public, the API treats money and authority with particular care. Adoption fees are computed twice — once provisionally when an application is submitted and once authoritatively at finalization — and a running ledger of net collected fees must always equal the sum of the fees of finalized, non-refunded adoptions. Euthanasia, the gravest action in the system, can never be requested and approved by the same person. These principles, and the precise rules that implement them, are the subject of the sections that follow.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes six roles, spelled exactly as follows: `ShelterAdmin`, `IntakeOfficer`, `Veterinarian`, `AdoptionCounselor`, `FosterCoordinator`, and `Adopter`. The single exception to authentication is the shelter-bootstrap operation that creates the initial shelter configuration, which may be invoked without an established user context; every other endpoint requires both headers.

Five of these roles are operational identities not tied to any persisted entity. When `X-User-Role` is `ShelterAdmin`, `IntakeOfficer`, `Veterinarian`, `AdoptionCounselor`, or `FosterCoordinator`, the accompanying `X-User-ID` is an opaque operator identifier; the server may record it where a workflow demands it — for example, a euthanasia review records the requesting operator's `X-User-ID` as `requested_by_user_id`, and a euthanasia approval records the approver's `X-User-ID` as `approved_by_user_id` — but it does not compare that identifier to any entity's `id`. The sixth role is entity-backed: when `X-User-Role` is `Adopter`, `X-User-ID` is the `id` of the acting `AdopterAccount`, and ownership checks on any resource that references an `AdopterAccount` (for instance, an adoption application's `adopter_id`) compare that foreign-key field to `X-User-ID`.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter caps the number of items returned; it defaults to 10, must be at least 1, and must not exceed 100. The `offset` parameter is the number of items to skip from the front of the result; it defaults to 0 and must be at least 0. A request whose `limit` falls outside the range of 1 to 100 inclusive, or whose `offset` is negative, is rejected with `ERR_VALIDATION_LIMIT`.

Unless a specific endpoint states otherwise, list results are sorted by the `created_at` timestamp in ascending order. The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources in the system carry a standard set of system-managed fields. Every resource is assigned an `id`, a server-minted UUID with no type prefix. Every resource records a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, fixed at creation. Resources that can be modified after creation additionally carry an `updated_at` timestamp, refreshed on every mutation, and a `version`, an integer that begins at its initial value and increments by one on each mutation.

One entity departs from this convention. A `Microchip` is an immutable registry row: it carries only `id` and `created_at`. It has no `updated_at` and no `version` field at all; once written, it is never mutated. Every other entity — `Shelter`, `Kennel`, `Animal`, `IntakeRecord`, `KennelAssignment`, `MedicalRecord`, `OwnerClaim`, `AdopterAccount`, `AdoptionApplication`, `FosterHome`, `FosterPlacement`, and `EuthanasiaDecision` — carries the full quartet of `id`, `created_at`, `updated_at`, and `version`.

Derived fields are first-class mutations. When the server recomputes a `Kennel`'s `occupied_count` and `status`, or advances a `Shelter`'s `collected_fee_cents`, or flips an `Animal`'s `microchipped` flag, it refreshes that resource's `updated_at` and increments its `version` exactly as it would for a client-driven change.

### 2.5. Cascading Outcomes and State Consistency

The shelter's outcome operations are atomic, multi-entity cascades, and every cascade completes wholly within the single request that triggers it. When an animal reaches a custody outcome — adoption, reclamation, or euthanasia — the system does not merely change the animal's own status; it also unwinds the animal's footprint elsewhere. The deepest of these chains originates at adoption finalization: finalizing an approved application marks the application `FINALIZED`, drives the animal to `ADOPTED`, releases the animal's currently `ACTIVE` kennel assignment, and decrements the occupancy of the kennel that assignment held — four coordinated mutations in one transaction. Reclamation and euthanasia trigger the same kennel-release-and-decrement tail from their own originating actions. Each entity touched in a cascade has its `updated_at` refreshed and its `version` incremented.

Animal custody and animal medical readiness are two independent state axes carried on the same `Animal` record. The `lifecycle_status` axis tracks where the animal sits in its custody journey; the `medical_status` axis tracks its clinical readiness. No operation advances both axes at once — a medical exam moves only `medical_status`, and an intake or outcome moves only `lifecycle_status` — so the two evolve on separate tracks and must both be consulted wherever a rule depends on readiness.

### 2.6. Resource Existence and Path Validation

Identifiers are validated left to right. For any request that carries a resource id in its path, that id must resolve to an existing resource; for any write whose body carries a foreign key (such as `animal_id`, `kennel_id`, `adopter_id`, `foster_home_id`, or `kennel_id`), each such reference must likewise resolve. References are checked in order, and the first unresolved identifier — whether a path id or a body foreign key — causes the request to be rejected with `ERR_NOT_FOUND` before any later reference is considered. On write endpoints, after existence is confirmed, the body is checked for required fields, correct types, and — for any enum-valued field — membership in that field's declared set; a missing required field, a wrong type, or an out-of-range enum value yields `ERR_INVALID_REQUEST`.

### 2.7. Validation Ordering

When several checks could apply to one request, they are evaluated in a fixed priority order so that the returned `error_id` is deterministic. Authentication comes first: a missing or malformed header surfaces as `ERR_UNAUTHENTICATED` before anything else is examined. Role authorization comes next, surfacing as `ERR_FORBIDDEN`. Then existence of every path id and body foreign key is confirmed, surfacing as `ERR_NOT_FOUND`. Then body shape — required fields, types, and enum membership — is checked, surfacing as `ERR_INVALID_REQUEST`; for list endpoints, the equivalent shape check is the pagination-bound check that surfaces as `ERR_VALIDATION_LIMIT`. Only after all of the above does the system evaluate state and business rules: first whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`), and then the domain-specific business constraints — chip-match, segregation of duties, stray-hold, medical clearance, kennel occupancy, foster capacity and cooldown, application conflict, uniqueness, and optimistic-concurrency — each described where its workflow lives in Section 3. In short: authentication, then authorization, then existence, then request shape, then transition legality, then business rules.

### 2.8. Monetary Precision and Rounding

All monetary amounts in the system are stored and returned as whole integer cents — board rates, surcharges, adoption fees, and the collected-fee ledger are never fractional. Wherever a calculation produces a fractional cent before it is stored (for example, when a percentage is applied to a base amount, or when a daily care surcharge is added to a board rate), the value is rounded to the nearest whole cent using the round-half-up convention, meaning a value exactly halfway between two cents rounds up to the larger cent. The specific points at which rounding occurs are pinned in the relevant calculation narratives in Section 3, because rounding order — rounding a per-day amount before summing it across days, rather than summing first and rounding once — changes the result.

### 2.9. Optimistic Concurrency on Kennel Assignment

Assigning an animal to a kennel is guarded by optimistic concurrency control against the kennel's `version`. The create-kennel-assignment operation requires the field `expected_kennel_version`, carrying the `version` of the target kennel as the client last observed it; this field is mandatory, not optional. If `expected_kennel_version` does not equal the kennel's current `version` — for instance, because another writer has already filled a single-occupancy kennel, raising its `occupied_count` and advancing its `version` since the client read it — the create is rejected with `ERR_STALE_VERSION` and HTTP status 412, before any occupancy mutation occurs. This is the only endpoint in the system that takes a version field; no other operation accepts or requires one.

### 2.10. The Logical Clock

Time-sensitive rules in this system — the stray-hold release gate, the foster cooldown buffer, and the board-cost day count — read from a server-controlled logical UTC clock rather than wall-clock time. An administrative test-driving capability sets this clock to a supplied instant, accepting that instant as the `to_iso8601` field and echoing the resulting clock value back as `now`; all subsequent system-assigned timestamps (such as an intake's `intake_at` or an assignment's `start_at`) and all "current time is at or after the release instant" gates read from the value last set. This makes the temporal rules deterministic and exercisable.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Shelter, Kennels, and Foster Homes

Before any animal moves through the system, a `ShelterAdmin` bootstraps the singleton shelter configuration by supplying a `name` and, optionally, overrides for the policy knobs the shelter runs on. The mandatory stray-hold period, `stray_hold_days`, defaults to 5 whole days and must be zero or greater. The promotional-pricing switch, `promo_active`, defaults to off. The two base board rates, `dog_daily_board_cents` and `cat_daily_board_cents`, default to 1850 and 1250 cents per day respectively. The shelter also carries a running ledger field, `collected_fee_cents`, which starts at zero and is described in 3.7. A `ShelterAdmin` may later read the configuration (including the live ledger) or amend policy — toggling `promo_active`, adjusting `stray_hold_days`, or revising either board rate — through an update operation; all five operational roles may read the configuration.

A `ShelterAdmin` provisions kennels. Each `Kennel` is created with a human-readable `label` and an optional `capacity`, the maximum number of concurrently `ACTIVE` assignments it can hold; capacity defaults to 1 (a single-occupancy kennel) and must be at least 1. The system maintains two derived fields on each kennel: `occupied_count`, the count of kennel assignments on it whose `status` is `ACTIVE`, which must equal that count at all times; and `status`, which reads `OPEN` while `occupied_count` is strictly less than `capacity` and `FULL` once `occupied_count` equals `capacity`. Kennels may be read individually or listed; the list view accepts an optional `status` filter alongside `limit` and `offset`.

A foster home is registered by a `ShelterAdmin` or a `FosterCoordinator` with a `contact_name` and two optional policy values: `max_concurrent`, the aggregate number of animals that may be on `ACTIVE` placement at the home simultaneously (default 2, at least 1), and `cooldown_days`, the required recovery gap in whole days between one placement ending and the next beginning at that home (default 3, zero or greater). Each `FosterHome` carries a derived `active_placement_count`, the number of its placements whose `status` is `ACTIVE`, which the system holds equal to that count at all times. Foster homes are readable individually and as a paginated list.

### 3.2. Animal Registration and Intake

An animal enters the system in two steps. First, a `ShelterAdmin` or `IntakeOfficer` registers an `Animal` record by supplying its `name`, its `species` (one of `DOG` or `CAT`, which selects the board rate), and its `age_months` (a whole number of months at intake, zero or greater, which later selects the adoption-fee age band). A freshly registered animal begins with `lifecycle_status` of `INTAKE_PENDING` and `medical_status` of `UNEXAMINED`; its `microchipped` flag is false and its `stray_hold_release_at` is null until intake. Any of the six roles may read an animal individually; the same set may list animals, filtering optionally by `lifecycle_status`, `medical_status`, and `species` in addition to `limit` and `offset`.

Intake is recorded by an `IntakeOfficer`. Intake is permitted only when the animal's `lifecycle_status` is `INTAKE_PENDING` and no prior intake record exists for that animal; otherwise the attempt is rejected with `ERR_INVALID_STATE`. The request names the `animal_id` and the `source` — one of `STRAY`, `SURRENDER`, or `TRANSFER` — and, for surrenders and transfers, the `surrendering_party` naming the relinquishing owner or transferring organization (this field is required for `SURRENDER` and `TRANSFER` and ignored for `STRAY`). Recording the intake stamps the server clock onto `intake_at`, computes the stray-hold release instant, drives the animal's `lifecycle_status` from `INTAKE_PENDING` to `IN_CUSTODY`, and copies the computed release instant onto both the intake record's `stray_hold_release_at` and the animal's `stray_hold_release_at`.

The stray-hold release instant is computed as follows. For a `STRAY` intake, it is the `intake_at` moment plus a number of hours equal to the shelter's `stray_hold_days` multiplied by 24 — that is, the configured number of whole days expressed in hours after intake. For a `SURRENDER` or `TRANSFER` intake, there is no hold: the release instant equals `intake_at` exactly. Downstream gates that consult this instant treat it as inclusive — an action attempted at the very instant of release is permitted, while an action one moment before it is not. Intake records are readable individually and as a list filterable by `animal_id` and `source`.

### 3.3. Medical Track and Microchip Registry

The `medical_status` axis ranges over `UNEXAMINED`, `EXAM_PENDING`, `NEEDS_TREATMENT`, and `CLEARED`. The medical axis is driven entirely by a `Veterinarian` recording a `MedicalRecord` against an animal. The record names the `animal_id` and a `record_type` — one of `EXAM`, `SPAY_NEUTER`, or `VACCINATION` — and may carry free-text `notes`. Only an `EXAM` moves the `medical_status` axis. An `EXAM` carries an `outcome` of `CLEAR` or `HOLD`: a `CLEAR` outcome sets `medical_status` to `CLEARED`, and a `HOLD` outcome sets it to `NEEDS_TREATMENT`. The `outcome` field is ignored for `SPAY_NEUTER` and `VACCINATION` records. An exam may be recorded while the animal's `medical_status` is `UNEXAMINED` or `NEEDS_TREATMENT`; from either of those, a `CLEAR` exam advances it to `CLEARED` and a `HOLD` exam (lawful from `UNEXAMINED` only as the first finding, and re-assertable while in `NEEDS_TREATMENT`) sets or keeps it at `NEEDS_TREATMENT`. Because `medical_status` is a parallel axis, none of this touches `lifecycle_status`. Medical records are readable individually and as a list filterable by `animal_id` and `record_type`.

The microchip registry is the system's proof-of-ownership backbone. A `Veterinarian` or `ShelterAdmin` registers a `Microchip` by naming the `animal_id` and a `chip_number`, optionally with the registered `owner_name` and `owner_phone`. The `chip_number` must be globally unique across all microchips; an attempt to register a serial already held by another chip is rejected with `ERR_DUPLICATE_CHIP`. Registering the first chip for an animal flips that animal's derived `microchipped` flag to true, which later feeds the adoption-fee microchip surcharge decision. Microchips are immutable once written. They may be read individually or looked up via a list filterable by `animal_id` and `chip_number`.

### 3.4. Kennel Assignment and Board Cost

An `IntakeOfficer` assigns an in-custody animal to a kennel by naming the `kennel_id`, the `animal_id`, and the `expected_kennel_version` described in 2.9. The assignment is permitted only when the animal's `lifecycle_status` is `IN_CUSTODY`, the target kennel's `status` is `OPEN` (its `occupied_count` strictly below its `capacity`), and no other `ACTIVE` assignment on that kennel overlaps the requested occupancy interval. Occupancy intervals are half-open, spanning from `start_at` up to but not including `end_at`; two intervals overlap when one begins before the other ends under that half-open convention. A kennel that is not `OPEN`, or on which an existing `ACTIVE` assignment overlaps the interval, causes rejection with `ERR_KENNEL_OCCUPIED`. A successful assignment is created with `status` `ACTIVE` and `start_at` stamped from the clock, increments the kennel's `occupied_count` by one, recomputes the kennel's `status` (to `FULL` if `occupied_count` now equals `capacity`), and increments the kennel's `version` by one.

A kennel assignment leaves the `ACTIVE` state either by an explicit release — invoked by a `ShelterAdmin` or `IntakeOfficer` — or as the tail of an animal-outcome cascade (adoption, reclamation, or euthanasia). Release is permitted only on an assignment whose `status` is `ACTIVE`. Releasing sets `end_at` to the current clock instant, transitions the assignment's `status` to `RELEASED`, computes the finalized board cost into `actual_board_cents`, decrements the kennel's `occupied_count` by one, recomputes the kennel's `status` (back to `OPEN` if `occupied_count` is again below `capacity`), and increments the kennel's `version` by one.

The finalized board cost is computed from the actual occupied interval. First, the number of occupied days is determined: take the elapsed time from `start_at` to `end_at`, divide it by 24 hours, round that quotient up to the next whole number, and then take the larger of that figure and 1 — so any occupancy of even part of a 24-hour window counts as a full day, and the minimum chargeable stay is one day. Next, the per-day base is selected by species: `dog_daily_board_cents` for a `DOG`, `cat_daily_board_cents` for a `CAT`. The per-day charged amount is that base increased by a 7.5 percent care fee — that is, the base multiplied by 1.075 — and this per-day amount is rounded to the nearest whole cent, half-up, before anything else. Finally, `actual_board_cents` is that rounded per-day charged amount multiplied by the number of occupied days. The rounding order is pinned: the per-day amount is rounded first and then multiplied by the day count; the alternative of multiplying first and rounding once is not used and would yield a different total.

A forward-looking projection of board cost is available as a read-only capability on an assignment, returning `projected_occupied_days` and `projected_board_cents`. The projection uses the same per-day rounding-then-multiply rule, but instead of the actual `end_at` it projects the occupied days from `start_at` forward to the animal's expected earliest release — its `stray_hold_release_at`. For a stray this assumes the full hold is served, so the projection diverges from the eventual actual cost whenever the animal is in fact released earlier. Kennel assignments are readable individually and as a list filterable by `kennel_id`, `animal_id`, and `status`.

### 3.5. From Custody to Available

An animal becomes adoptable only when an `AdoptionCounselor` moves it to `AVAILABLE`, and that move is the system's central readiness gate. It is permitted only from `lifecycle_status` `IN_CUSTODY`, and only when every readiness condition holds. The animal's `medical_status` must be `CLEARED`; if it is not, the request is rejected with `ERR_NOT_MEDICALLY_CLEARED`. The stray-hold must have elapsed — the current clock instant must be at or after the animal's `stray_hold_release_at` — and if it has not, the request is rejected with `ERR_STRAY_HOLD_ACTIVE`. The animal must additionally have no `OwnerClaim` still in `PENDING`, since an open ownership claim must be resolved before the animal can be offered for adoption. When all of these hold, the animal's `lifecycle_status` advances from `IN_CUSTODY` to `AVAILABLE`.

### 3.6. Return to Owner

A return-to-owner claim lets a prior owner reclaim an in-custody animal. A `ShelterAdmin` or `IntakeOfficer` opens an `OwnerClaim` against an animal whose `lifecycle_status` is `IN_CUSTODY`, naming the `animal_id`, the `claimant_name`, and optionally a `proof_chip_number` — the microchip serial the claimant presents as evidence of ownership. A new claim begins in `status` `PENDING`. Only a `ShelterAdmin` may resolve a claim, either approving or denying it; both actions require the claim to be in `PENDING`.

Approving a claim is the proof-of-ownership checkpoint. It requires that the animal's `lifecycle_status` still be `IN_CUSTODY` and that the claim's `proof_chip_number` match the `chip_number` of an existing microchip registered on that same animal; if the presented serial matches no microchip on the animal, the approval is rejected with `ERR_CHIP_MISMATCH`. On a successful approval, the claim's `status` becomes `APPROVED`, the animal is driven from `IN_CUSTODY` to `RECLAIMED`, and the animal's `ACTIVE` kennel assignment, if any, is released with the attendant occupancy decrement. Denying a claim simply sets its `status` to `DENIED` and has no effect on the animal. Owner claims are readable individually and as a list filterable by `animal_id` and `status`.

### 3.7. Adoption: Application, Review, Finalization, and Refund

The adoption pipeline begins when an `Adopter` (or an `AdoptionCounselor` acting on their behalf) registers an `AdopterAccount` with a `full_name`, an `email`, and an optional `phone`. The `email` must be unique across all adopter accounts; a duplicate is rejected with `ERR_DUPLICATE_EMAIL`. An adopter account is readable by a `ShelterAdmin`, an `AdoptionCounselor`, or the owning `Adopter`.

An application is submitted against an `AVAILABLE` animal, naming the `animal_id` and the `adopter_id`. Submission is permitted only while the animal's `lifecycle_status` is `AVAILABLE` and no other application for that animal sits in `APPROVED` or `FINALIZED`; otherwise it is rejected with `ERR_INVALID_STATE`. A new application begins in `status` `SUBMITTED`, and at submission the system computes a provisional fee into `estimated_fee_cents`. From `SUBMITTED`, the application forks: an `AdoptionCounselor` either approves it (advancing `status` to `APPROVED`) or rejects it (advancing `status` to `REJECTED`, a terminal outcome with no effect on the animal). Approval is the more heavily guarded branch: it requires the application to be in `SUBMITTED`, the animal to be `AVAILABLE`, the animal's `medical_status` to be `CLEARED` (else `ERR_NOT_MEDICALLY_CLEARED`), and no other application for the same animal to already be in `APPROVED` or `FINALIZED` (else `ERR_APPLICATION_CONFLICT`); only then does `status` become `APPROVED`. Rejection requires only that the application be in `SUBMITTED`.

Finalization is performed by an `AdoptionCounselor` and is the deepest cascade in the system. It requires the application to be in `APPROVED` and the animal to still be `AVAILABLE`. On finalization, the system recomputes the fee into `final_fee_cents`, sets the application `status` to `FINALIZED`, adds `final_fee_cents` to the shelter's `collected_fee_cents`, drives the animal from `AVAILABLE` to `ADOPTED`, and releases the animal's `ACTIVE` kennel assignment with the occupancy decrement that entails.

The adoption fee is computed by the same tiered rule at two moments, differing only in when the inputs are read. The evaluation order is fixed: first the age band, then the base fee, then the microchip surcharge, then the promotional discount, then the floor. The age band is `PUPPY_KITTEN` when the animal's `age_months` is under 6; it is `SENIOR` when `age_months` is at least 84; otherwise it is `ADULT`. The base fee follows the band: 25000 cents for `PUPPY_KITTEN`, 15000 cents for `ADULT`, and 5000 cents for `SENIOR`. A microchip surcharge of 2500 cents is added when the animal's `microchipped` flag is false, and nothing is added when it is true; the gross amount is the base plus this surcharge. If the shelter's `promo_active` is on, a discount applies: compute 20 percent of the gross, rounded to the nearest cent half-up, and take the larger of that percentage amount and a flat 3000 cents — the discount is whichever of those two is greater. If `promo_active` is off, the discount is zero. The fee is then the gross minus the discount, but never below a floor of 0 cents — that is, the larger of zero and (gross minus discount). The provisional computation at submission reads the animal's `microchipped` flag and the shelter's `promo_active` as they stand at submit time and stores the result in `estimated_fee_cents`; the final computation at finalization re-reads both inputs as they stand at finalize time and stores the result in `final_fee_cents`. If the animal was microchipped or the promotion was toggled in between, `final_fee_cents` will differ from `estimated_fee_cents`. The `final_fee_cents` field is null until the application is `FINALIZED`.

A finalized adoption may be refunded by a `ShelterAdmin`. Refund requires the application to be in `FINALIZED`. It sets the application's `refunded` flag to true and its `status` to `REFUNDED`, and as a compensating action it subtracts `final_fee_cents` back out of the shelter's `collected_fee_cents`. This keeps the ledger invariant intact: `collected_fee_cents` always equals the sum of `final_fee_cents` across applications that are `FINALIZED` and not yet refunded. Applications are readable individually and as a list filterable by `animal_id`, `adopter_id`, and `status`.

### 3.8. Foster Placement and Return

When an animal is `AVAILABLE`, a `FosterCoordinator` may place it into a foster home, naming the `foster_home_id` and the `animal_id`. Placement is gated on three conditions. The animal's `lifecycle_status` must be `AVAILABLE`. The home must have aggregate room: its `active_placement_count` must be strictly less than its `max_concurrent`, and a placement attempted when the count already equals the maximum is rejected with `ERR_FOSTER_HOME_FULL`. And the home's cooldown must have cleared: the new placement's `start_at` must fall at least `cooldown_days` whole days after the `end_at` of the most recent `RETURNED` placement at that home, otherwise the attempt is rejected with `ERR_FOSTER_COOLDOWN`. A successful placement creates a `FosterPlacement` in `status` `ACTIVE` with `start_at` stamped from the clock, increments the home's `active_placement_count` by one, and drives the animal from `AVAILABLE` to `FOSTERED`.

Foster placement intervals are closed — they span from `start_at` through `end_at` inclusive — and a returned placement additionally reserves the `cooldown_days` window after its `end_at` before the home is eligible to host again. Returning a placement is performed by a `FosterCoordinator` and is permitted only on a placement whose `status` is `ACTIVE`. The return sets the placement's `end_at` to the current clock instant, transitions its `status` to `RETURNED`, decrements the home's `active_placement_count` by one, and drives the animal from `FOSTERED` back to `AVAILABLE`. The lifecycle is deliberately cyclic: a returned animal is `AVAILABLE` again and may be placed into a fresh `FosterPlacement` or proceed to adoption. Foster placements are readable individually and as a list filterable by `foster_home_id`, `animal_id`, and `status`.

### 3.9. Euthanasia Under Dual Control

Euthanasia is the system's most tightly controlled outcome and is deliberately split across two distinct actors. The review is opened by an `AdoptionCounselor` or `ShelterAdmin` against an animal whose `lifecycle_status` is `IN_CUSTODY`, naming the `animal_id` and a documented `reason` — one of `MEDICAL_UNTREATABLE`, `BEHAVIORAL`, or `COURT_ORDER`. Opening the review records the caller's `X-User-ID` into `requested_by_user_id` and starts the decision in `status` `REQUESTED`.

From `REQUESTED`, a `Veterinarian` either approves or rejects the decision. Approval enforces segregation of duties: the approving `Veterinarian`'s `X-User-ID` must differ from the decision's `requested_by_user_id`, and an attempt by the same person who requested it to also approve it is rejected with `ERR_SEGREGATION_OF_DUTIES`. A valid approval records the approver's `X-User-ID` into `approved_by_user_id` and sets `status` to `APPROVED`. Rejection requires only that the decision be in `REQUESTED` and simply sets `status` to `REJECTED` with no effect on the animal.

Execution is the final, irreversible step, performed by a `Veterinarian` on a decision in `status` `APPROVED`. It requires the animal's `lifecycle_status` to still be `IN_CUSTODY` and — critically for strays — the stray-hold to have elapsed, meaning the current clock instant is at or after the animal's `stray_hold_release_at`; an execution attempted during an active hold is rejected with `ERR_STRAY_HOLD_ACTIVE`, so a stray can never be euthanized while its reclamation window is still open. A valid execution sets the decision's `status` to `EXECUTED`, drives the animal from `IN_CUSTODY` to `EUTHANIZED`, and releases the animal's `ACTIVE` kennel assignment with the usual occupancy decrement. Euthanasia decisions are readable individually and as a list filterable by `animal_id` and `status`.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that read a resource or modify an existing one — including state transitions such as approvals, finalizations, releases, and returns — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/shelters` | Bootstrap the shelter configuration | (bootstrap, no auth) ShelterAdmin |
| GET | `/shelters/{id}` | Read shelter config and ledger | ShelterAdmin, IntakeOfficer, AdoptionCounselor, Veterinarian, FosterCoordinator |
| PATCH | `/shelters/{id}` | Update shelter policy | ShelterAdmin |
| POST | `/kennels` | Create a kennel | ShelterAdmin |
| GET | `/kennels/{id}` | Read a kennel | ShelterAdmin, IntakeOfficer, AdoptionCounselor, Veterinarian, FosterCoordinator |
| GET | `/kennels` | List kennels | ShelterAdmin, IntakeOfficer, AdoptionCounselor, Veterinarian, FosterCoordinator |
| POST | `/animals` | Register an animal record | ShelterAdmin, IntakeOfficer |
| GET | `/animals/{id}` | Read an animal | ShelterAdmin, IntakeOfficer, AdoptionCounselor, Veterinarian, FosterCoordinator, Adopter |
| GET | `/animals` | List animals with filters | ShelterAdmin, IntakeOfficer, AdoptionCounselor, Veterinarian, FosterCoordinator, Adopter |
| POST | `/animals/{id}/make-available` | Move a cleared, hold-elapsed animal to AVAILABLE | AdoptionCounselor |
| POST | `/intake-records` | Record an intake; drives animal to IN_CUSTODY | IntakeOfficer |
| GET | `/intake-records/{id}` | Read an intake record | ShelterAdmin, IntakeOfficer, AdoptionCounselor, Veterinarian |
| GET | `/intake-records` | List intake records | ShelterAdmin, IntakeOfficer, AdoptionCounselor, Veterinarian |
| POST | `/kennel-assignments` | Assign an in-custody animal to an OPEN kennel | IntakeOfficer |
| GET | `/kennel-assignments/{id}` | Read a kennel assignment | ShelterAdmin, IntakeOfficer, AdoptionCounselor, Veterinarian, FosterCoordinator |
| GET | `/kennel-assignments` | List kennel assignments | ShelterAdmin, IntakeOfficer, AdoptionCounselor, Veterinarian, FosterCoordinator |
| GET | `/kennel-assignments/{id}/projected-board` | Forward-looking projected board cost | ShelterAdmin, IntakeOfficer, AdoptionCounselor |
| POST | `/kennel-assignments/{id}/release` | Release an active assignment | ShelterAdmin, IntakeOfficer |
| POST | `/medical-records` | Record an exam, spay-neuter, or vaccination | Veterinarian |
| GET | `/medical-records/{id}` | Read a medical record | ShelterAdmin, Veterinarian, AdoptionCounselor |
| GET | `/medical-records` | List medical records | ShelterAdmin, Veterinarian, AdoptionCounselor |
| POST | `/microchips` | Register a microchip for an animal | Veterinarian, ShelterAdmin |
| GET | `/microchips/{id}` | Read a microchip registry entry | ShelterAdmin, Veterinarian, AdoptionCounselor, IntakeOfficer |
| GET | `/microchips` | List or look up microchips | ShelterAdmin, Veterinarian, AdoptionCounselor, IntakeOfficer |
| POST | `/owner-claims` | Open a return-to-owner claim | ShelterAdmin, IntakeOfficer |
| GET | `/owner-claims/{id}` | Read an owner claim | ShelterAdmin, IntakeOfficer, AdoptionCounselor |
| GET | `/owner-claims` | List owner claims | ShelterAdmin, IntakeOfficer, AdoptionCounselor |
| POST | `/owner-claims/{id}/approve` | Approve a claim; cascades animal to RECLAIMED | ShelterAdmin |
| POST | `/owner-claims/{id}/deny` | Deny a claim | ShelterAdmin |
| POST | `/adopter-accounts` | Register an adopter account | ShelterAdmin, AdoptionCounselor, Adopter |
| GET | `/adopter-accounts/{id}` | Read an adopter account | ShelterAdmin, AdoptionCounselor, Adopter |
| POST | `/adoption-applications` | Submit an adoption application | Adopter, AdoptionCounselor |
| GET | `/adoption-applications/{id}` | Read an adoption application | ShelterAdmin, AdoptionCounselor, Adopter |
| GET | `/adoption-applications` | List adoption applications | ShelterAdmin, AdoptionCounselor, Adopter |
| POST | `/adoption-applications/{id}/approve` | Approve a submitted application | AdoptionCounselor |
| POST | `/adoption-applications/{id}/reject` | Reject a submitted application | AdoptionCounselor |
| POST | `/adoption-applications/{id}/finalize` | Finalize; computes final fee, cascades animal to ADOPTED | AdoptionCounselor |
| POST | `/adoption-applications/{id}/refund` | Refund a finalized adoption | ShelterAdmin |
| POST | `/foster-homes` | Register a foster home | ShelterAdmin, FosterCoordinator |
| GET | `/foster-homes/{id}` | Read a foster home | ShelterAdmin, FosterCoordinator |
| GET | `/foster-homes` | List foster homes | ShelterAdmin, FosterCoordinator |
| POST | `/foster-placements` | Place an available animal into a foster home | FosterCoordinator |
| GET | `/foster-placements/{id}` | Read a foster placement | ShelterAdmin, FosterCoordinator |
| GET | `/foster-placements` | List foster placements | ShelterAdmin, FosterCoordinator |
| POST | `/foster-placements/{id}/return` | Return a fostered animal to AVAILABLE | FosterCoordinator |
| POST | `/euthanasia-decisions` | Open a euthanasia review | AdoptionCounselor, ShelterAdmin |
| GET | `/euthanasia-decisions/{id}` | Read a euthanasia decision | ShelterAdmin, AdoptionCounselor, Veterinarian |
| GET | `/euthanasia-decisions` | List euthanasia decisions | ShelterAdmin, AdoptionCounselor, Veterinarian |
| POST | `/euthanasia-decisions/{id}/approve` | Approve a decision (dual-control) | Veterinarian |
| POST | `/euthanasia-decisions/{id}/reject` | Reject a decision | Veterinarian |
| POST | `/euthanasia-decisions/{id}/execute` | Execute; cascades animal to EUTHANIZED | Veterinarian |
| POST | `/_clock/set` | Set the server's logical UTC clock (test-driving) | ShelterAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_VALIDATION_LIMIT` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CHIP_MISMATCH` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_STRAY_HOLD_ACTIVE` | 409 |
| `ERR_NOT_MEDICALLY_CLEARED` | 409 |
| `ERR_KENNEL_OCCUPIED` | 409 |
| `ERR_FOSTER_HOME_FULL` | 409 |
| `ERR_FOSTER_COOLDOWN` | 409 |
| `ERR_APPLICATION_CONFLICT` | 409 |
| `ERR_DUPLICATE_CHIP` | 409 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_STALE_VERSION` | 412 |
</content>
</invoke>
