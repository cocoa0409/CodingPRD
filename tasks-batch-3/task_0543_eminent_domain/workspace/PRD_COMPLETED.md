# Eminent Domain & Right-of-Way Acquisition API — Product Requirements Document

## 1. Introduction

Acquiring land for a public right-of-way is a slow, adversarial, and heavily regulated undertaking. A condemning agency must research who owns each parcel, commission an independent appraisal, extend a good-faith just-compensation offer, negotiate through rounds of offers and counteroffers, and — where negotiation fails — file a condemnation action, deposit statutory compensation with the court, take possession, and ultimately have a court fix the final award. In parallel it must relocate displaced occupants, move utilities out of the take area, and settle every dollar through escrow while never overspending the program's budget. Each of these threads has its own lifecycle, its own eligible actors, and its own fiscal and procedural guardrails, yet they all converge on a single physical parcel.

This document specifies a REST API that models the full acquisition lifecycle end to end. The system is organized around a **Project** (a funded right-of-way program) that contains many **Parcels**, each of which carries two independent status dimensions — an ownership-research track and an acquisition-lifecycle track — that evolve simultaneously. Downstream entities (appraisals, negotiations, condemnations, relocation benefits, utility relocations, and escrows) hang off the parcel and drive it forward. Because acquisition is a multi-party negotiation layered on top of a compliance audit trail, the API enforces strict role separation, optimistic concurrency on parcel valuation, cascading state propagation across aggregates, and a set of statutory fiscal floors and ceilings. The sections below define the global contract first, then the business workflows, and finally the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, envelopes, and cross-cutting principles that govern every endpoint. All resource paths are mounted at the server root.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. If `X-User-Role` is missing or does not name a recognized role, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the header is present and recognized but the acting role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly six roles, spelled precisely as follows:

- **`ProgramAdmin`** — the program administrator and court proxy. Owns project creation, judicial actions (granting possession, entering the final award), escrow rescission, and control of the logical clock.
- **`RightOfWayAgent`** — the agency's acquisition agent. Owns parcel and ownership research, agency-side offers, condemnation filing and deposit, and relocation review.
- **`Appraiser`** — the independent appraiser. Owns appraisal authoring, finalization, and inspection scheduling.
- **`PropertyOwner`** — the property owner or occupant acting on their own parcel. Owns owner-side offer rounds and relocation claims.
- **`EscrowOfficer`** — the escrow and title officer. Owns the escrow lifecycle, disbursement, and relocation payout.
- **`UtilityCoordinator`** — the utility relocation coordinator. Owns identifying, scheduling, and completing utility relocations.

Five of these roles carry an **opaque** identity. When `X-User-Role` is `ProgramAdmin`, `RightOfWayAgent`, `Appraiser`, `EscrowOfficer`, or `UtilityCoordinator`, the `X-User-ID` value is an opaque operator identifier that is not tied to any persisted entity. The server may record such an identifier where a workflow calls for it, but it never compares it to any entity's `id` for ownership purposes.

`PropertyOwner` is different: it is **entity-backed** by an `OwnershipInterest`. When `X-User-Role` is `PropertyOwner`, `X-User-ID` is the `id` of the acting `OwnershipInterest` record. Any ownership check on a parcel-scoped resource compares that resource's parcel against the acting interest: the acting `OwnershipInterest` must belong to the parcel named in the path — that is, its `id` must equal `X-User-ID` and its `parcel_id` must match the path parcel. A `PropertyOwner` whose `X-User-ID` is not an `OwnershipInterest` of the target parcel is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership check applies to owner-party negotiation rounds and to relocation-benefit submission.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A `limit` or `offset` outside these ranges, or that cannot be parsed as an integer, is rejected with `ERR_PAGINATION_INVALID` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources in the system are full first-class entities that carry a standard set of system-managed fields:

- **`id`** — a unique, server-minted identifier formatted as a UUID with no type prefix.
- **`created_at`** — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. This and `updated_at` are stamped from real server (wall-clock) time, not from the logical clock of §2.5.
- **`updated_at`** — an ISO 8601 UTC timestamp recording the most recent modification. It is refreshed on every mutation.
- **`version`** — an integer that starts at 1 on creation and increments by one on every mutation of the resource. It is the basis for optimistic concurrency control (see §2.7).

The full-entity treatment applies to `Project`, `Parcel`, `OwnershipInterest`, `Appraisal`, `InspectionAppointment`, `Negotiation`, `RelocationBenefit`, `Condemnation`, `UtilityRelocation`, and `Escrow`.

The **`OfferRound`** entity is the sole exception. An offer round is an append-only event in a negotiation ledger: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because it is never modified after creation.

### 2.5. The Logical Clock

Time in this system is a server-managed logical clock rather than wall-clock time. On startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any clock-setting call it holds that default and never falls back to the host's real time. A `ProgramAdmin` may advance or reset the clock by supplying a `to_iso8601` instant; the endpoint responds with the new `current_utc`. Every timestamp the workflows record — an appraisal inspection window, a deposit's `deposit_at`, a possession's `possession_at`, an escrow's `funded_at`, and all waiting-period and interest computations — is read from this logical clock. This makes temporal rules such as the escrow waiting period and statutory-interest accrual deterministic and test-drivable.

### 2.6. Monetary Values, Precision, and Rounding

Every monetary amount in the system is stored and transmitted as an integer number of cents; field names carrying money end in `_cents`. Because inputs are already integer cents, sums and differences are exact and require no rounding. Two calculations do introduce fractional intermediate values — the disbursement waterfall's per-owner shares and the statutory-interest and prompt-bonus percentage terms — and in every such case the result is rounded to the nearest whole cent using the **round half up** convention (a value ending in exactly one-half cent rounds away from zero to the next cent). Percentages and daily interest rates are applied as decimal multipliers and only the final monetary product is rounded.

### 2.7. Optimistic Concurrency Control on Parcel Valuation

Creating a new appraisal against a parcel is guarded by optimistic concurrency control keyed on the parcel's `version`. A request that creates a draft appraisal for a parcel must carry an `expected_parcel_version` field that holds the client's last observed `version` of that `Parcel`. Because a new appraisal legitimately supersedes the parcel's prior draft and recomputes the parcel's valuation, a create that arrives with an `expected_parcel_version` that does not match the parcel's current `version` is working from an outdated view of the parcel and is rejected with `ERR_STALE_VERSION` (HTTP 412). The `expected_parcel_version` field is required on appraisal creation; no other endpoint accepts or requires a version field.

### 2.8. Nested Resource Retrieval and Path Validation

Many endpoints address a resource nested beneath a parent — for example a parcel beneath a project, or an inspection appointment beneath an appraisal. For any request whose path carries multiple identifiers, the system validates their existence in strict left-to-right order and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the *first* identifier that does not resolve to an existing resource. A request naming a child under a non-existent parent therefore fails on the parent before the child is ever looked up. This ordering holds for reads and writes alike.

### 2.9. Cascading State Consistency

A single operation frequently mutates more than one entity, and the system keeps those entities consistent automatically rather than requiring the client to issue follow-up calls. Whenever a cascade updates an entity, that entity's `updated_at` is refreshed and its `version` is incremented in the same way a direct mutation would be. The specific cascades — an appraisal finalization rewriting the parcel's valuation and superseding the prior appraisal, a negotiation acceptance advancing the parcel's acquisition status, a possession grant flipping utility-relocation possession flags, and an escrow close (or its rescission) moving the parcel into or out of its acquired status while re-deriving the project's ledger — are described in full within the workflows of §3. The governing rule here is that these secondary effects are the server's responsibility and are applied atomically with the triggering action.

### 2.10. The Project Budget Ledger

Each `Project` maintains a live budget derived from its parcels and escrows; these are read-only computed fields, never written directly. A parcel's `appraised_value_cents` counts as **committed** while the parcel is actively being acquired: `committed_cents` is the sum of `appraised_value_cents` over the project's parcels whose `acquisition_status` is one of `IN_NEGOTIATION`, `AGREED`, `IN_CONDEMNATION`, or `POSSESSED`. Once money actually leaves the project, it counts as **disbursed**: `disbursed_cents` is the sum of `agreed_amount_cents` over the project's escrows whose `status` is `CLOSED`. The **acquired footprint**, `acquired_area_sqft`, is the sum of `take_area_sqft` over the project's parcels whose `acquisition_status` is `ACQUIRED`. Finally, `available_cents` is `total_budget_cents` minus `committed_cents` minus `disbursed_cents`. Note that a parcel leaves the committed set precisely when its escrow closes and it becomes `ACQUIRED`, at which moment its money shifts from the committed column to the disbursed column.

### 2.11. Order of Validation

When several checks could reject a request, they are evaluated in a fixed priority order so that the earliest applicable failure is the one reported. The order is:

1. **Authentication** — a recognized `X-User-Role` must be present, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the acting role must be permitted for the operation, else `ERR_FORBIDDEN` (403).
3. **Path existence** — every id in the path must resolve, left to right, else `ERR_NOT_FOUND` (404).
4. **Resource ownership** — for owner-party negotiation rounds and relocation submission, the acting `PropertyOwner` must be an `OwnershipInterest` of the target parcel, else `ERR_NOT_RESOURCE_OWNER` (403).
5. **Body well-formedness** — required fields present, enum values valid, and numeric constraints satisfied, else `ERR_VALIDATION` (400).
6. **State** — the target resource must be in a state that permits the transition, else the domain-specific state error (409).
7. **Turn ordering** — on a negotiation round, it must be the acting party's turn, else `ERR_NOT_YOUR_TURN` (409).
8. **Concurrency** — `expected_parcel_version` must match on appraisal creation, else `ERR_STALE_VERSION` (412).
9. **Ownership completeness** — where required, fee ownership must total 100 percent, else `ERR_OWNERSHIP_INCOMPLETE` (422).
10. **Cross-entity readiness** — ownership cleared, appraisal finalized, good-faith negotiation attempted, or occupant eligibility, per the specific readiness error (422).
11. **Temporal rules** — appraiser appointment overlap, crew buffer, and escrow waiting period (409).
12. **Fiscal floors and ceilings** — offer floor, deposit floor, and budget ceiling (402).

## 3. Business Logic & Workflows

### 3.1. Establishing the Program and Its Parcels

The acquisition program begins when a `ProgramAdmin` creates a **Project**, supplying a `name`, an `agency_name`, and a `total_budget_cents` that must be zero or greater. On creation the project's `committed_cents`, `disbursed_cents`, and `acquired_area_sqft` all begin at zero and `available_cents` equals the full `total_budget_cents`; thereafter these ledger figures are recomputed by the workflows described throughout §3 and in §2.10. Any role may read a project or list the parcels belonging to it.

A `RightOfWayAgent` populates the program by creating **Parcels**. Each parcel names its owning project through `project_id` — which must reference an existing project, else the create is rejected with `ERR_NOT_FOUND` — carries an assessor parcel number `apn` that is unique within the project (a create whose `apn` duplicates an existing parcel's `apn` in the same project is rejected with `ERR_VALIDATION`), and records a `total_area_sqft` (which must be strictly greater than zero) and a `take_area_sqft` (which must be strictly greater than zero and no larger than `total_area_sqft`). A create in which the take area exceeds the total area is malformed and rejected with `ERR_VALIDATION`. The `take_type` enumerates whether the acquisition is a `FULL` or `PARTIAL` take.

A crucial structural fact about a parcel is that it advances along **two independent status dimensions at once**. The ownership-research dimension, `research_status`, begins at `RESEARCHING` and terminates at `OWNERSHIP_CLEARED`. The acquisition-lifecycle dimension, `acquisition_status`, begins at `PENDING` and terminates at `ACQUIRED`, passing through `IN_NEGOTIATION`, `AGREED`, `IN_CONDEMNATION`, and `POSSESSED` along the way. These two tracks live on the same parcel row but evolve separately; neither is derived from the other. A freshly created parcel starts at `RESEARCHING` / `PENDING` with `appraised_value_cents` at zero. Any parcel-driving operation invoked when the parcel is not in a `research_status` or `acquisition_status` that permits it — for example, opening a negotiation on a parcel that is not `PENDING` — is rejected with `ERR_INVALID_PARCEL_STATE`.

### 3.2. Researching Ownership and Clearing Title

Before an agency can negotiate, it must know who holds an interest in the land. A `RightOfWayAgent` records each stake as an **OwnershipInterest** against a parcel, providing an `interest_type` of `FEE_OWNER`, `LIENHOLDER`, `TENANT`, or `EASEMENT_HOLDER`, together with a `holder_name`. Additional attributes qualify the interest: `ownership_pct` is the holder's percentage of fee ownership, meaningful only for a `FEE_OWNER`, defaulting to zero and constrained to the inclusive range from 0 to 100; `lien_priority` is the payoff priority for a `LIENHOLDER`, where a lower number is paid first and the default is zero; `lien_balance_cents` is the outstanding lien balance for a `LIENHOLDER`, defaulting to zero; and `is_occupant` is a boolean, defaulting to false, marking whether this holder physically occupies the parcel and is therefore relocation-eligible. Any role may list the ownership interests of a parcel.

Clearing ownership research is a `RightOfWayAgent` action that advances the parcel's `research_status` from `RESEARCHING` to `OWNERSHIP_CLEARED`. It succeeds only when fee ownership is fully accounted for: the sum of `ownership_pct` across the parcel's `FEE_OWNER` interests must equal exactly 100. If it does not, the clear is rejected with `ERR_OWNERSHIP_INCOMPLETE`. This same 100-percent completeness rule is enforced again later, at escrow close, so that title is provably whole both before negotiation opens and before money is disbursed.

### 3.3. Appraisal, Just Compensation, and Inspection Scheduling

An `Appraiser` values a parcel by creating an **Appraisal**, which references the parcel and records an `appraiser_name`, a `land_value_cents` and `improvements_value_cents` (each zero or greater), and optional `severance_damages_cents` and `special_benefits_cents` (each defaulting to zero and constrained to be zero or greater). From these the system derives two distinct bases. The **offer basis**, stored as `just_compensation_cents`, is `land_value_cents` plus `improvements_value_cents` plus the greater of zero and the quantity (`severance_damages_cents` minus `special_benefits_cents`) — that is, special benefits offset severance damages but can never drive the severance term below zero. The **condemnation basis**, stored as `condemnation_basis_cents`, is `land_value_cents` plus `improvements_value_cents` plus the full `severance_damages_cents`, with special benefits *not* offset. Consequently the two bases differ by exactly the smaller of `severance_damages_cents` and `special_benefits_cents`. Both figures are exact integer cents. The offer basis is what feeds the parcel's `appraised_value_cents` and the negotiation offer floor; the condemnation basis is what the court deposit floor is snapshotted from.

Creating an appraisal is subject to the parcel-version concurrency control of §2.7: the create must carry an `expected_parcel_version` equal to the parcel's current `version`, or it is rejected with `ERR_STALE_VERSION`. A newly created appraisal starts in `status` `DRAFT`; if the parcel already had a `DRAFT` appraisal, that prior draft is moved to `SUPERSEDED`. Every appraisal creation increments the parcel's `version` by one.

Finalization is a separate `Appraiser` action that moves an appraisal's `status` from `DRAFT` to `FINALIZED`; attempting to finalize an appraisal that is not in `DRAFT` yields `ERR_INVALID_APPRAISAL_STATE`. Finalization carries three effects that must all occur together. First, any *other* appraisal for the same parcel that was previously `FINALIZED` is transitioned from `FINALIZED` to `SUPERSEDED`, so that a parcel has at most one live finalized valuation. Second, the parcel's `appraised_value_cents` is set to this appraisal's `just_compensation_cents`; because that valuation changed, the project's `committed_cents` is recomputed whenever the parcel currently sits in a committed acquisition status. Third, the parcel's `version` is incremented by one.

Independently of valuation, an `Appraiser` schedules a site visit by creating an **InspectionAppointment** under an appraisal. The appointment references its appraisal through `appraisal_id`, names the `appraiser_name` acting as the resource being booked, and defines a half-open window from `start_at` (inclusive) to `end_at` (exclusive), where `end_at` must be strictly after `start_at`; a window with `end_at` at or before `start_at` is rejected with `ERR_VALIDATION`. An appointment is created in `status` `SCHEDULED`, which is its only state. The appraiser named on an appointment is treated as a bookable resource: a new window that overlaps any existing appointment window for the same `appraiser_name` is rejected with `ERR_APPRAISER_DOUBLE_BOOKED`. Any role may list the inspection appointments of an appraisal.

### 3.4. Negotiation: Offers, Counters, and Prompt Settlement

Once a parcel's title is cleared and it carries a finalized valuation, a `RightOfWayAgent` opens a **Negotiation** against the parcel with an `initial_offer_cents`. Opening a negotiation advances the parcel's `acquisition_status` from `PENDING` to `IN_NEGOTIATION` and prompts a recomputation of the project's `committed_cents`, since the parcel now contributes its `appraised_value_cents` to the committed column. Opening requires that the parcel's `research_status` be `OWNERSHIP_CLEARED` — otherwise `ERR_OWNERSHIP_NOT_CLEARED` — and that the parcel have a `FINALIZED` appraisal — otherwise `ERR_APPRAISAL_NOT_FINALIZED`. The offer floor is fiscal: the `initial_offer_cents` may not fall below the parcel's `appraised_value_cents`; an under-floor opening is rejected with `ERR_OFFER_BELOW_APPRAISED`. A new negotiation is created in `status` `AGENCY_OFFERED`, its `initial_offer_cents` recorded, and its ledger seeded with a first offer round numbered 1, whose `party` is `AGENCY` and whose `action` is `OFFER` at the opening amount.

The negotiation then proceeds as a **cyclic exchange of rounds**. Each round is captured as an append-only `OfferRound` referencing the negotiation through `negotiation_id`, stamped with a one-based `round_no`, a `party` of `AGENCY` or `OWNER` derived from the acting role, and an `action` of `OFFER`, `COUNTER`, `ACCEPT`, or `REJECT`. For an `OFFER` or `COUNTER` the round carries an `amount_cents`; that amount is required for those two actions and omitted (defaulting to zero) for `ACCEPT` and `REJECT`. The negotiation exposes `current_amount_cents`, the amount of the most recent offer or counter, and `round_count`, the total number of offer rounds recorded.

Turn discipline governs who may act. When the negotiation is in `AGENCY_OFFERED`, the standing offer is the agency's and it is the owner's turn; a `PropertyOwner` may counter it, accept it, or reject it. When the negotiation is in `OWNER_COUNTERED`, the standing counter is the owner's and it is the agency's turn; a `RightOfWayAgent` may counter, re-offer, accept, or reject. A round submitted by the party whose turn it is *not* is rejected with `ERR_NOT_YOUR_TURN`, and a round submitted against a negotiation that has already reached a terminal outcome is rejected with `ERR_INVALID_NEGOTIATION_STATE`. A counter from either side appends a new round with `round_no` equal to the prior `round_count` plus one, flips the negotiation to the other party's turn (`AGENCY_OFFERED` becomes `OWNER_COUNTERED` when the owner counters, and `OWNER_COUNTERED` returns to `AGENCY_OFFERED` when the agency counters or re-offers), and sets `current_amount_cents` to the countered amount. A `REJECT` from whichever party holds the turn appends a rejecting round and drives the negotiation to the terminal `IMPASSE`.

An `ACCEPT` settles the negotiation. When the owner accepts a standing agency offer from `AGENCY_OFFERED`, or the agency accepts a standing owner counter from `OWNER_COUNTERED`, the system appends the accepting round, sets the negotiation's `agreed_amount_cents` to the standing `current_amount_cents`, moves the negotiation to `AGREED`, and cascades the parcel's `acquisition_status` from `IN_NEGOTIATION` to `AGREED`.

Reaching `AGREED` also computes a **prompt-settlement bonus** that rewards a quick deal. The bonus is keyed on the negotiation's `round_count` at the moment of agreement — this count includes the accepting round itself — and on the `agreed_amount_cents` as the base. If the negotiation took more than two rounds to settle (that is, `round_count` exceeds the maximum bonus round of 2), no bonus is paid and `prompt_bonus_cents` is zero. Otherwise a tiered percentage applies: if `agreed_amount_cents` is at most 25,000,000 cents (a threshold of \$250,000), the low rate of 3 percent applies; if it is above that threshold, the high rate of 5 percent applies. The `prompt_bonus_cents` is the `agreed_amount_cents` multiplied by the selected rate, rounded half up to a whole cent. The negotiation's `settlement_total_cents` is then the `agreed_amount_cents` plus the `prompt_bonus_cents`; the tier is always determined from the base agreed amount, never from the settlement total. When a negotiation does not reach `AGREED`, both `prompt_bonus_cents` and `settlement_total_cents` remain zero. Any role may read a negotiation, list a parcel's negotiations, or list a negotiation's rounds.

### 3.5. Condemnation: Filing, Deposit, Possession, and Award

When negotiation stalls, a `RightOfWayAgent` files a **Condemnation** against the parcel. Filing is gated on a genuine good-faith effort: the parcel must have cleared ownership (else `ERR_OWNERSHIP_NOT_CLEARED`), must carry a `FINALIZED` appraisal (else `ERR_APPRAISAL_NOT_FINALIZED`), and must have a negotiation on which at least one offer round was recorded (else `ERR_NEGOTIATION_NOT_ATTEMPTED`). On filing, the condemnation captures `just_compensation_snapshot_cents` — the `condemnation_basis_cents` of the parcel's finalized appraisal — which serves as the statutory deposit floor. A filed condemnation starts in `status` `FILED`, and the parcel's `acquisition_status` cascades from `IN_NEGOTIATION` to `IN_CONDEMNATION`.

The agent then deposits statutory compensation with the court. Depositing requires the condemnation to be in `FILED` (else `ERR_INVALID_CONDEMNATION_STATE`) and requires the supplied `deposit_amount_cents` to be at least the `just_compensation_snapshot_cents` floor (else `ERR_DEPOSIT_BELOW_COMPENSATION`). A valid deposit records `deposit_amount_cents`, stamps `deposit_at` from the logical clock, and moves the condemnation to `DEPOSIT_MADE`.

A `ProgramAdmin`, acting as the court, then grants an order of possession. Granting possession moves the condemnation from `DEPOSIT_MADE` to `POSSESSED`, stamps `possession_at` from the logical clock, and cascades the parcel's `acquisition_status` from `IN_CONDEMNATION` to `POSSESSED`. That parcel transition in turn flips the `possession_cleared` flag to true on every utility relocation of the parcel that was still awaiting possession (see §3.7).

Finally the court fixes the award. A `ProgramAdmin` enters the `final_award_cents`, moving the condemnation from `POSSESSED` to `AWARDED`. Entering the award computes **statutory interest** on the shortfall between the award and the earlier deposit, accrued over the days the agency held possession before the award. The number of whole days is the interval from `possession_at` to the current clock, expressed in seconds, divided by 86,400 seconds and truncated down to a whole number of days. The `statutory_interest_cents` is then the quantity (`final_award_cents` minus `deposit_amount_cents`) multiplied by the statutory daily interest rate of 0.0001 (one hundredth of one percent per day) multiplied by that day count, with the resulting interest term rounded half up to a whole cent. The condemnation's `settlement_total_cents` is the `final_award_cents` plus the `statutory_interest_cents`. Any role may read a condemnation or list a parcel's condemnations.

### 3.6. Relocation Assistance for Displaced Occupants

An occupant displaced by the take may claim relocation assistance. A `PropertyOwner` submits a **RelocationBenefit** against the parcel, naming the `claimant_name` and an `occupant_type` of `RESIDENTIAL` or `BUSINESS`, which selects the benefit formula. Because only an occupant is eligible, the acting `OwnershipInterest` (identified through the owner's `X-User-ID`, per §2.1) must have `is_occupant` equal to true; a claim from a non-occupant is rejected with `ERR_NOT_OCCUPANT`. The claim payload also carries the inputs the chosen variant needs: for a residential claim, the `comparable_replacement_cost_cents` and the `acquired_dwelling_price_cents`; for a business claim, the `reestablishment_cost_cents`; and in both cases a documented `moving_expense_cents`. Each of these amounts defaults to zero when omitted.

The `benefit_amount_cents` is computed at submission from the selected variant. For a `RESIDENTIAL` occupant, the replacement-housing differential is the greater of zero and (`comparable_replacement_cost_cents` minus `acquired_dwelling_price_cents`), capped at 3,150,000 cents (\$31,500); the `benefit_amount_cents` is that capped differential plus the `moving_expense_cents`. For a `BUSINESS` occupant, the reestablishment component is the `reestablishment_cost_cents` capped at 5,000,000 cents (\$50,000); the `benefit_amount_cents` is that capped component plus the `moving_expense_cents`. A submitted benefit starts in `status` `SUBMITTED`.

Review is a `RightOfWayAgent` responsibility: the agent either approves a submitted benefit, moving it from `SUBMITTED` to `APPROVED`, or denies it — optionally supplying a `reason`, which is neither required nor persisted on or returned with the benefit — moving it from `SUBMITTED` to `DENIED`. An `EscrowOfficer` then pays an approved benefit, moving it from `APPROVED` to `PAID`. Any approve, deny, or pay attempt against a benefit that is not in the required originating state is rejected with `ERR_INVALID_RELOCATION_STATE`. Any role may read a relocation benefit or list a parcel's benefits.

### 3.7. Utility Relocation

Utilities inside the take area must be moved before the land can be used. A `UtilityCoordinator` first identifies each affected utility by creating a **UtilityRelocation** against the parcel with a `utility_type` of `WATER`, `GAS`, `ELECTRIC`, `TELECOM`, or `SEWER`. A newly identified relocation starts in `status` `IDENTIFIED`, with `crew_name` empty and `scheduled_start` and `scheduled_end` unset. Its `possession_cleared` flag is set at creation to reflect whether the parcel has already reached `POSSESSED` or `ACQUIRED`; otherwise the flag is false and will be flipped to true later by the cascade from a possession grant (see §3.5).

Scheduling a crew is gated on possession and on crew availability. A schedule action is permitted only when `possession_cleared` is true — equivalently, when the parcel's `acquisition_status` is `POSSESSED` or `ACQUIRED`; a schedule attempted before then is rejected with `ERR_PARCEL_NOT_POSSESSED`. The action supplies a `crew_name` and a half-open window from `scheduled_start` (inclusive) to `scheduled_end` (exclusive). The named crew is a shared resource that needs turnaround time between jobs: if any other `SCHEDULED` relocation for the same `crew_name` has a window that falls within the configured crew buffer (the `CREW_BUFFER_MINUTES` separation, which is 60 minutes) of this window, the schedule is rejected with `ERR_CREW_UNAVAILABLE`. A successful schedule records the crew and window and moves the relocation from `IDENTIFIED` to `SCHEDULED`. The coordinator later marks the work done, moving it from `SCHEDULED` to `RELOCATED`. Any transition attempted from the wrong state is rejected with `ERR_INVALID_UTILITY_STATE`. Any role may read a utility relocation or list a parcel's relocations.

### 3.8. Escrow, Disbursement, and Final Settlement

Money changes hands through escrow. An `EscrowOfficer` opens an **Escrow** against the parcel, declaring a `source` of `NEGOTIATED` or `CONDEMNATION` that determines where the agreed money comes from. A `NEGOTIATED` escrow requires the parcel's negotiation to have reached `AGREED`, else `ERR_INVALID_NEGOTIATION_STATE`; a `CONDEMNATION` escrow requires the parcel's condemnation to have reached `AWARDED`, else `ERR_INVALID_CONDEMNATION_STATE`. At creation the escrow captures its `agreed_amount_cents` from the source's settlement figure — the negotiation's `settlement_total_cents` for a negotiated escrow, or the condemnation's `settlement_total_cents` for a condemnation escrow. A new escrow starts in `status` `OPENED` with `funded_amount_cents` and `disbursed_total_cents` at zero and `disbursements` empty.

Funding draws the money from the program budget. Funding is permitted only when the project's `available_cents` is at least the escrow's `agreed_amount_cents`; a fund that would overrun the budget is rejected with `ERR_BUDGET_EXCEEDED`. A successful fund sets `funded_amount_cents` equal to `agreed_amount_cents`, stamps `funded_at` from the logical clock, and moves the escrow from `OPENED` to `FUNDED`.

Closing settles the acquisition, and it is doubly gated. First, title must be whole: the sum of `ownership_pct` across the parcel's `FEE_OWNER` interests must equal 100, else `ERR_OWNERSHIP_INCOMPLETE`. Second, a statutory waiting period must have elapsed: the logical clock must be at or beyond `funded_at` plus the configured escrow waiting period (`ESCROW_WAITING_PERIOD_DAYS`, which is 3 days), else `ERR_WAITING_PERIOD_ACTIVE`. A close attempted from any state other than `FUNDED` is rejected with `ERR_INVALID_ESCROW_STATE`.

On a valid close the system runs the **disbursement waterfall** over the parcel's ownership interests and populates the escrow's `disbursements` array, where each row records a `payee_label`, a `payee_kind`, and an `amount_cents`. The pool to distribute is the `agreed_amount_cents`. First, lienholders are paid: the parcel's `LIENHOLDER` interests are taken in ascending `lien_priority`, breaking ties by ascending `created_at`, and each is paid the lesser of the remaining pool and its `lien_balance_cents`, with that payment deducted from the pool and recorded as a disbursement whose `payee_kind` is `LIENHOLDER`. Whatever remains is then split among the `FEE_OWNER` interests by ownership share, with the rounding order pinned so the payout always sums exactly. Specifically, each fee owner's raw share is the remaining pool multiplied by that owner's `ownership_pct` divided by 100; each raw share is rounded half up to a whole cent; the leftover delta (the pool minus the sum of the rounded shares) is added to the fee owner with the earliest `created_at`; and each adjusted share is recorded as a disbursement whose `payee_kind` is `FEE_OWNER`. By construction the sum of every `amount_cents` in `disbursements` equals the `agreed_amount_cents` exactly. Closing sets `disbursed_total_cents` to `agreed_amount_cents`, moves the escrow from `FUNDED` to `CLOSED`, and cascades the parcel's `acquisition_status` to `ACQUIRED`; the project's `disbursed_cents` and `acquired_area_sqft` are recomputed as the parcel's money moves from committed to disbursed and its `take_area_sqft` joins the acquired footprint.

The escrow lifecycle also allows a `ProgramAdmin` to **rescind** as a compensating action. Rescinding an `OPENED` or `FUNDED` escrow simply moves it to `CANCELLED`; rescinding an escrow already in `CANCELLED` is rejected with `ERR_INVALID_ESCROW_STATE`. Rescinding a `CLOSED` escrow unwinds the settlement: the escrow moves to `CANCELLED`, its `disbursements` are cleared and its `disbursed_total_cents` reset to zero, and the parcel's `acquisition_status` cascades from `ACQUIRED` back to `PENDING`, with the project's `disbursed_cents` and `acquired_area_sqft` both decreasing back to their pre-close values. Any role may read an escrow (including its `disbursements` once closed) or list a parcel's escrows.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including state transitions, the clock-set utility, and every action endpoint — return `200 OK`. Read operations return `200 OK`. In the table below, "Any" denotes that all six recognized roles may invoke the read.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | ProgramAdmin |
| POST | `/projects` | Create a right-of-way project | ProgramAdmin |
| GET | `/projects/{id}` | Get a project with computed ledger fields | Any |
| GET | `/projects/{id}/parcels` | List parcels of a project | Any |
| POST | `/parcels` | Create a parcel under a project | RightOfWayAgent |
| GET | `/parcels/{id}` | Get a parcel | Any |
| POST | `/parcels/{id}/clear-ownership` | Mark ownership research complete | RightOfWayAgent |
| POST | `/parcels/{id}/ownership-interests` | Record an ownership/lien/tenancy interest | RightOfWayAgent |
| GET | `/parcels/{id}/ownership-interests` | List ownership interests of a parcel | Any |
| POST | `/parcels/{id}/appraisals` | Create a draft appraisal (OCC-guarded) | Appraiser |
| GET | `/appraisals/{id}` | Get an appraisal | Any |
| GET | `/parcels/{id}/appraisals` | List appraisals of a parcel | Any |
| POST | `/appraisals/{id}/finalize` | Finalize a draft appraisal | Appraiser |
| POST | `/appraisals/{id}/inspection-appointments` | Schedule an appraiser inspection window | Appraiser |
| GET | `/appraisals/{id}/inspection-appointments` | List inspection appointments of an appraisal | Any |
| POST | `/parcels/{id}/negotiations` | Open a negotiation with an initial offer | RightOfWayAgent |
| GET | `/negotiations/{id}` | Get a negotiation | Any |
| GET | `/parcels/{id}/negotiations` | List negotiations of a parcel | Any |
| POST | `/negotiations/{id}/rounds` | Append an offer round | RightOfWayAgent, PropertyOwner |
| GET | `/negotiations/{id}/rounds` | List offer rounds of a negotiation | Any |
| POST | `/parcels/{id}/condemnations` | File a condemnation action | RightOfWayAgent |
| GET | `/condemnations/{id}` | Get a condemnation | Any |
| GET | `/parcels/{id}/condemnations` | List condemnations of a parcel | Any |
| POST | `/condemnations/{id}/deposit` | Deposit statutory compensation | RightOfWayAgent |
| POST | `/condemnations/{id}/grant-possession` | Grant an order of possession | ProgramAdmin |
| POST | `/condemnations/{id}/award` | Enter the final award | ProgramAdmin |
| POST | `/parcels/{id}/relocation-benefits` | Submit a relocation-assistance claim | PropertyOwner |
| GET | `/relocation-benefits/{id}` | Get a relocation benefit | Any |
| GET | `/parcels/{id}/relocation-benefits` | List relocation benefits of a parcel | Any |
| POST | `/relocation-benefits/{id}/approve` | Approve a submitted relocation benefit | RightOfWayAgent |
| POST | `/relocation-benefits/{id}/deny` | Deny a submitted relocation benefit | RightOfWayAgent |
| POST | `/relocation-benefits/{id}/pay` | Pay an approved relocation benefit | EscrowOfficer |
| POST | `/parcels/{id}/utility-relocations` | Identify a utility to relocate | UtilityCoordinator |
| GET | `/utility-relocations/{id}` | Get a utility relocation | Any |
| GET | `/parcels/{id}/utility-relocations` | List utility relocations of a parcel | Any |
| POST | `/utility-relocations/{id}/schedule` | Schedule a crew window | UtilityCoordinator |
| POST | `/utility-relocations/{id}/complete` | Mark a utility relocation complete | UtilityCoordinator |
| POST | `/parcels/{id}/escrows` | Open escrow for an agreed or awarded acquisition | EscrowOfficer |
| GET | `/escrows/{id}` | Get an escrow with disbursements when closed | Any |
| GET | `/parcels/{id}/escrows` | List escrows of a parcel | Any |
| POST | `/escrows/{id}/fund` | Fund the escrow from project budget | EscrowOfficer |
| POST | `/escrows/{id}/close` | Close escrow, run the waterfall, complete acquisition | EscrowOfficer |
| POST | `/escrows/{id}/rescind` | Rescind an escrow (compensating action) | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_PAGINATION_INVALID` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_PARCEL_STATE` | 409 Conflict |
| `ERR_INVALID_APPRAISAL_STATE` | 409 Conflict |
| `ERR_INVALID_NEGOTIATION_STATE` | 409 Conflict |
| `ERR_NOT_YOUR_TURN` | 409 Conflict |
| `ERR_INVALID_CONDEMNATION_STATE` | 409 Conflict |
| `ERR_INVALID_RELOCATION_STATE` | 409 Conflict |
| `ERR_INVALID_ESCROW_STATE` | 409 Conflict |
| `ERR_INVALID_UTILITY_STATE` | 409 Conflict |
| `ERR_OWNERSHIP_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_OWNERSHIP_NOT_CLEARED` | 422 Unprocessable Entity |
| `ERR_APPRAISAL_NOT_FINALIZED` | 422 Unprocessable Entity |
| `ERR_NEGOTIATION_NOT_ATTEMPTED` | 422 Unprocessable Entity |
| `ERR_NOT_OCCUPANT` | 422 Unprocessable Entity |
| `ERR_PARCEL_NOT_POSSESSED` | 409 Conflict |
| `ERR_APPRAISER_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_CREW_UNAVAILABLE` | 409 Conflict |
| `ERR_WAITING_PERIOD_ACTIVE` | 409 Conflict |
| `ERR_OFFER_BELOW_APPRAISED` | 402 Payment Required |
| `ERR_DEPOSIT_BELOW_COMPENSATION` | 402 Payment Required |
| `ERR_BUDGET_EXCEEDED` | 402 Payment Required |
