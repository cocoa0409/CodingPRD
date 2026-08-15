# Traveling Exhibit Tours API — Product Requirements Document

## 1. Introduction

A traveling exhibition company lives or dies by its route. Each tour packs a complete exhibit into a fleet of crates, books a sequence of host venues, and then shepherds those crates through shipping, installation, public opening, teardown, and — when the calendar allows — a refurbishment interlude before the next city. Every stop carries a participation contract whose fee is shaped by how many visitors actually walk through the door and softened by whatever local sponsorship the venue can raise; every leg between venues must be insured, inspected, and reconciled before the next gallery may open.

This document specifies the Traveling Exhibit Tours API, the operational backbone for that business. It covers venue registration and route booking, participation fee calculation with attendance tiers and sponsorship credits, crate inventory and inter-venue shipments, condition inspection and damage claims, marketing kit production, insurance certificates, refurbishment windows, and tour retirement. Most resources are namespaced under the `/tours` URL prefix; venue registration and the logical clock sit outside it. The API is consumed by five peer roles — tour management, venue staff, exhibit registrars, freight shippers, and insurers — each owning a distinct slice of the workflow, while the server itself performs the time- and event-driven transitions that keep the hierarchy consistent.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring their operational capacity. The system recognizes exactly five roles: `TourManager`, the exhibition company's operations manager, who owns the tour lifecycle, bookings, contracts, and marketing; `VenueRegistrar`, host-venue registration staff who sign contracts and report attendance; `Registrar`, the exhibit registrar responsible for condition inspection and reports; `Shipper`, the freight carrier driving shipment dispatch and departure; and `Insurer`, the insurance carrier issuing certificates and adjudicating claims.

A request missing either header, or presenting an unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A well-identified caller attempting an operation reserved for another role is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

For every one of these roles — `TourManager`, `VenueRegistrar`, `Registrar`, `Shipper`, and `Insurer` — identity is opaque: `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record it where a workflow calls for attribution (for example, as the `supervisor_user_id` recorded when a supervisor is assigned to a stop) but never compares it against any resource's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter says how many items to skip and defaults to 0. Unless stated otherwise, every list endpoint returns resources sorted by their creation timestamp, `created_at` ascending. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope. Many collections additionally accept resource-specific filters: a `status` filter recurs across tours, stops, shipments, reports, claims, marketing kits, and certificates, and identifier filters such as `venue_id`, `tour_id`, `tour_stop_id`, `shipment_id`, `crate_id`, `condition_report_id`, `origin_stop_id`, `destination_stop_id`, `current_stop_id`, `location_status`, and `phase` appear on the nested and flat collection reads described throughout §3.

### 2.4. Logical Time and the Certificate Clock

The server keeps a logical clock that never reads wall-clock time. Before any client call, the logical clock reads exactly 2026-08-01T00:00:00Z — a fixed startup default. A `TourManager`-only test-driving capability advances it: the caller supplies a `to_iso8601` instant and receives back the resulting `current_utc`. Insurance certificates ride this clock: a certificate in `ISSUED` becomes `ACTIVE` once the logical clock reaches its `effective_from`, and a certificate in `ACTIVE` becomes `EXPIRED` once the logical clock reaches its `effective_to`. Coverage windows are therefore half-open — inclusive at `effective_from`, exclusive at `effective_to` — and advancing the clock is the mechanism that performs these activations and expirations; no client transitions a certificate directly.

### 2.5. Common Resource Properties

Every resource in the system — tours, venues, tour stops, participation contracts, crates, shipments, condition reports, damage claims, marketing kits, and insurance certificates — carries four system-managed properties:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): an integer that increments by one on every mutation of the resource, enabling optimistic concurrency control where the API calls for it.

Automatic reconciliations count as mutations like any other: when the system re-computes a tour's billing totals, moves a crate's location, or cascades a retirement, each affected resource has its `updated_at` refreshed and its `version` incremented.

### 2.6. Money, Condition Scores, and Rounding Discipline

All money in the system is integer cents. Participation fees, sponsorship credits, declared values, coverage amounts, claim amounts, payouts, and kit costs are stored and returned as whole cents with no fractional part. Whenever a percentage is applied to a monetary figure, the product is rounded half-up to the nearest whole cent, and multi-step calculations round at exactly the steps their rule in §3 pins down — never earlier, never later. Condition scores are integers from 0 to 100, likewise produced by round-half-up. Every threshold and percentage quoted in §3 is exact; there is no approximation anywhere in the financial or scoring pipeline.

### 2.7. Optimistic Concurrency Control on Route Booking

Exactly one write in the API is guarded by optimistic concurrency control: booking a new stop onto a tour. The booking request must carry `expected_tour_version`, holding the tour `version` the client last observed. If that value does not match the tour's current `version` — because another booking or mutation has advanced the tour since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), so route-sequencing decisions are never taken against a superseded route snapshot. A successful booking itself increments the tour's `version` by one, meaning each appended stop invalidates the snapshot the next writer may be holding. Endpoints other than stop booking do not accept a version field.

### 2.8. Nested Resource Resolution and Validation Ordering

Paths nest deeply in this API: a condition report lives under a shipment under a tour. The server resolves path identifiers left to right — tour first, then the stop or shipment within it, then the report or claim within that — and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource, without examining the remainder of the path.

Where several checks guard a single request, they fire in a fixed order rather than text order: authentication, then authorization, then left-to-right path existence, then the stale-version rejection on the one OCC-guarded write, then transition state validity — a transition attempted from a state that does not permit it fails with `ERR_INVALID_STATE` (HTTP 409) — and finally the business rules, applied in the priority order documented for each operation in §3. Independent of this ordering, a payload that is missing a required field, carries an unrecognized enum value, or is otherwise malformed is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.9. Tour Posture and Cross-Entity Cascades

The tour's own `status` — `DRAFT`, `BOOKING`, `ON_TOUR`, `IN_REFURBISHMENT`, or the terminal `RETIRED` — is a posture that gates everything below it: installation at a stop can begin only while the tour is `BOOKING`, `ON_TOUR`, or `IN_REFURBISHMENT`, and retirement is refused while committed stops or open damage claims remain. Many transitions are performed by the system rather than by any client call: the tour leaves `BOOKING` for `ON_TOUR` when its first stop begins installing, slips into `IN_REFURBISHMENT` when the calendar opens a sufficient gap after a stop closes, and returns to `ON_TOUR` when the next stop begins installing. Retiring a tour cascades through every aggregate it owns — stops, contracts, marketing kits, certificates, and crates (§3.9) — and cancelling a contracted stop cascades through its own children in the same spirit (§3.8). The same posture logic drives shipments: crates change hands between venue, transit, and refurbishment in step with the stop and shipment transitions that §3 narrates.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Tour: Tours, Venues, and Crate Inventory

A `TourManager` opens the engagement by creating the tour itself, supplying a `title`, an `exhibit_code` that must remain unique across all tours (something like DINOSAURS-2026), the `crate_count` of crates that make up the exhibit, the insured `declared_value_cents` of the whole exhibit, and the `refurbishment_gap_days` — the minimum number of refurbishment days the exhibit needs between consecutive stops, which may be zero but never negative. A new tour is born in `DRAFT` with its three ledger totals — `total_billed_cents`, `total_collected_cents`, and `total_waived_cents` — all initialized to zero. Tours can be listed with a `status` filter and read individually by id.

Venues are registered as a separate reference pool, each with a `name`, its host `city`, a `climate_controlled` flag describing whether the gallery environment is controlled, the `max_gallery_sqm` of gallery square meters available to the exhibit, and the `local_sponsorship_cap_cents` ceiling on the local sponsorship dollars the venue may raise against its participation fee. That cap resurfaces at contract signature time (§3.3).

Crates join the tour's inventory one at a time, each registered with a `crate_label` that must be unique within its tour (CRATE-07 and the like) and a `contents_value_cents` declaring what the contents are worth. A crate is born with `location_status` `AT_ORIGIN`, a null `condition_score`, and an empty `current_stop_id` — that pointer stays empty while the crate sits at origin and otherwise identifies the stop the crate is currently at or bound for. From origin the crate's `location_status` walks `AT_ORIGIN` → `IN_TRANSIT` → `AT_VENUE`, with `IN_REFURBISHMENT` as a fourth posture reached when the exhibit pauses between cities (§3.9). A tour's crate collection lists with a `location_status` filter, and a flat crate listing spanning tours filters by `tour_id`, `current_stop_id`, or `location_status`.

Booking opens only once the exhibit physically exists: a `TourManager` issues a tour lifecycle transition whose `action` is `OPEN_BOOKING`, moving the tour `DRAFT` → `BOOKING`. The move requires a positive `crate_count` and at least one crate already registered in the inventory; attempting it before both hold — or from any state other than `DRAFT` — is rejected with `ERR_INVALID_STATE`.

### 3.2. Booking the Route: Stops, Windows, and Sequencing

Route building is the OCC-guarded heart of the system. Booking a stop takes a payload naming the `venue_id`, the four window timestamps `install_start`, `open_date`, `close_date`, and `teardown_end`, the `projected_attendance` the venue expects, and the concurrency token `expected_tour_version` (§2.7). The stop is born `TENTATIVE`, stamped with a `seq` fixing its route position, and its `supervision_required` flag is computed on the spot: true whenever the host venue is not `climate_controlled`, or the tour's `crate_count` exceeds the climate-exempt crate ceiling. A stop flagged `supervision_required` cannot begin installation until a supervisor is on record (§3.8). Every successful booking increments the parent tour's `version` by one.

The `seq` assignment is purely chronological: the new stop's position is one plus the number of existing stops of the same tour — of any status whatsoever, live or cancelled — that sort strictly earlier, where "earlier" means an earlier `install_start`, or an identical `install_start` paired with an earlier `created_at`. That `created_at` ascending comparison is the only tie-break; there are no random or identifier-based fallbacks.

Four rejections guard stop booking, and they are evaluated in a fixed order. First comes the stale-version check: a mismatched `expected_tour_version` fails with `ERR_STALE_VERSION` before any business rule is consulted. Second, venue double-booking: if any other stop at the same venue — considering only stops in `TENTATIVE`, `CONTRACTED`, `INSTALLING`, `OPEN`, or `TEARDOWN` — holds a window overlapping the new one, the booking fails with `ERR_VENUE_DOUBLE_BOOKED`; overlap is measured on the half-open interval that includes `install_start` and excludes `teardown_end`, so a stop whose install begins exactly when another's teardown ends does not conflict. Third, the refurbishment gap: consecutive stops of the same tour must leave at least `refurbishment_gap_days` between the previous stop's `teardown_end` and the next stop's `install_start`, or the booking fails with `ERR_REFURBISHMENT_GAP_VIOLATED`. Fourth and last, window shape: the four timestamps must strictly increase from `install_start` to `open_date` to `close_date` to `teardown_end`, or the booking fails with `ERR_WINDOW_MALFORMED` (HTTP 422).

While a stop remains `TENTATIVE`, a `TourManager` or the `VenueRegistrar` may revise its `projected_attendance` through the stop update capability; if a provisional fee has already been computed for the stop's contract, that provisional figure is recomputed from the new projection. The same update capability records the `actual_attendance` — the final visitor count, zero or more — once the venue reports it, and closing the stop is impossible until it has been reported (§3.8). Stops list per tour with `venue_id` and `status` filters, and a flat stop collection spans tours with `tour_id`, `venue_id`, and `status` filters.

Supervision deserves one more word. When `supervision_required` is true, a `TourManager` assigns an on-site installation supervisor through a dedicated assignment capability that records a `supervisor_user_id` — a registrar operator's id — against the stop and returns that `supervisor_user_id` together with the `tour_stop_id` it was attached to. This single act is what satisfies the supervision gate at installation time.

### 3.3. Participation Contracts, Tiered Fees, and Sponsorship Credit

Each stop monetizes through a participation contract, created by a `TourManager` with a `base_fee_cents` and the `sponsorship_credit_cents` the venue commits against its fee. A stop may carry at most one non-terminal contract: attempting to create a second while an earlier one is still open fails with `ERR_DUPLICATE_CONTRACT`. Reading a stop's contract returns a list, since finalized contracts are retained alongside any live one. A contract is born `DRAFT`, and its `final_fee_cents` stays null until the contract is finalized.

The contract lifecycle runs `DRAFT` → `SENT` → `SIGNED` → `FINALIZED`, with one amendment loop. Sending (`action` `SEND`, by the `TourManager`) moves `DRAFT` → `SENT` and computes `provisional_fee_cents` on the spot. If terms need rework, the manager revokes (`REVOKE`), looping `SENT` → `DRAFT` so the contract can be amended before signature. Signature (`SIGN`) belongs to the `VenueRegistrar` alone: at that moment the committed `sponsorship_credit_cents` is checked against the venue's `local_sponsorship_cap_cents`, and an over-cap commitment is refused with `ERR_SPONSORSHIP_OVER_CAP`. A successful signature flips the stop `TENTATIVE` → `CONTRACTED` and credits the tour's `total_waived_cents` with the waiver actually applied — the smaller of the contract's `sponsorship_credit_cents` and its `provisional_fee_cents`.

The participation fee comes in three variants off a single tiered formula. Attendance drives an uplift on the base fee: attendance of at most ten thousand draws no uplift; above ten thousand and at most fifty thousand, the uplift is ten percent of `base_fee_cents`; above fifty thousand, it is twenty-five percent. The uplift is rounded half-up to whole cents. The fee before credit is the base plus the uplift; the sponsorship credit actually applied is the smallest of three figures — the contract's `sponsorship_credit_cents`, the venue's `local_sponsorship_cap_cents`, and that fee before credit — and the fee is what remains after the credit is subtracted. Evaluation order is pinned exactly so: tier uplift first, then the credit cap, then the subtraction. The PROVISIONAL variant, computed at send time, feeds the stop's `projected_attendance` through this formula and lands in `provisional_fee_cents`. The FINAL variant, computed when the stop closes (§3.8), feeds `actual_attendance` through the same formula and lands in `final_fee_cents`. The FINAL_CANCEL variant applies when a `CONTRACTED` stop is cancelled: the final fee is thirty percent of the provisional fee, rounded half-up to whole cents — the sponsorship credit has already been absorbed inside the provisional figure, so no credit is subtracted a second time.

Finalization is always system-performed, never a client act. Closing a stop finalizes its `SIGNED` contract with the FINAL variant; cancelling a `CONTRACTED` stop finalizes with the FINAL_CANCEL penalty; cancelling a `TENTATIVE` stop finalizes any non-finalized contract on it with `final_fee_cents` of zero — no fee is due on a stop that never contracted; and retiring a tour finalizes every contract still standing (§3.9). Whenever a final fee lands, the tour's `total_billed_cents` — the sum of final participation fees billed across all its stops — is recomputed. Fee payments applied to a contract accumulate in its `amount_paid_cents` and roll up into the tour-wide `total_collected_cents`.

### 3.4. Marketing Kits and Local Press

Alongside the contract, a `TourManager` may plan the stop's marketing kit, supplying a `language_count` of language editions to produce and the number of `sponsor_logo_slots` the venue has sold to local sponsors. The kit is born `PLANNED` with `press_release_sent` false. Kits list per stop and through a flat collection filterable by `tour_stop_id` and `status`.

Production (`action` `PRODUCE`) is permitted while the stop is `TENTATIVE` or `CONTRACTED` and stamps the kit's `production_cost_cents`. The cost builds in layers: a fixed base of $1,500.00; plus $450.00 per language edition — and when `language_count` strictly exceeds three, the language portion alone earns a fifteen percent bulk discount, rounded half-up to whole cents at the moment the discount is applied; plus $200.00 per sponsor logo slot. The logo slots never discount.

Delivery moves `PRODUCED` → `DELIVERED` (`action` `DELIVER`) and demands two things at once: the stop must be in `CONTRACTED`, `INSTALLING`, or `OPEN`, and the press release must already have been issued to the venue. Issuing it is a separate `TourManager` capability that marks the kit's `press_release_sent` true; a delivery attempted before that mark fails with `ERR_INVALID_STATE`. Kits still sitting in `PLANNED` or `PRODUCED` are swept to `RETIRED` by the system when their stop is cancelled or their tour retires; a `DELIVERED` kit survives both events untouched.

### 3.5. Insuring the Exhibit

No crate moves and no installation begins without paper behind it. The `Insurer` issues certificates into a tour, each naming the `tour_stop_id` it covers, the `insurer_name`, the `coverage_cents` amount — which must be at least the tour's `declared_value_cents` — and the coverage window `effective_from` through `effective_to`. A certificate is born `ISSUED`; the logical clock carries it `ISSUED` → `ACTIVE` when time reaches `effective_from` and `ACTIVE` → `EXPIRED` when time reaches `effective_to` (§2.4). Two further transitions are punitive rather than temporal: a stop cancellation or a tour retirement voids the stop's certificates, moving them from `ISSUED` or `ACTIVE` into terminal `VOID`. Certificates list per tour with `tour_stop_id` and `status` filters, and a flat collection spans tours with `tour_id` and `tour_stop_id` filters.

One coverage rule gates both shipment dispatch and installation start, and a certificate counts as covering a leg only when all four of its clauses hold together: the certificate's `status` is `ISSUED` or `ACTIVE`; its `coverage_cents` is at least the tour's `declared_value_cents`; its `effective_from` falls at or before the leg's `depart_at`; and its `effective_to` falls strictly after the leg's `arrive_at` — the window's end is exclusive. When no certificate satisfying all four clauses covers the destination stop, the dispatch or the installation start is rejected with `ERR_NO_INSURANCE_COVERAGE` (HTTP 409).

### 3.6. Moving the Crates: Shipment Legs

Between every pair of consecutive stops runs a shipment leg. A `Shipper` or a `TourManager` plans the leg with the `origin_stop_id` the crates depart from — null only for the first leg of the tour, which departs the origin inventory — the `destination_stop_id` they are bound for, the `depart_at` and `arrive_at` timestamps, the `carrier_name`, and the `crate_ids` that form the shipment's manifest. The shipment is born `PLANNED` with its crate manifest recorded. The destination must be a stop of the same tour, and whenever an origin is given, origin and destination must be consecutive stops by route `seq`; a plan violating either clause is rejected with `ERR_ROUTE_NOT_CONSECUTIVE`. Shipments list per tour with `destination_stop_id` and `status` filters, and a flat shipment collection spans tours with `tour_id`, `origin_stop_id`, or `destination_stop_id` filters.

The leg's lifecycle runs `PLANNED` → `DISPATCHED` → `IN_TRANSIT` → `RECEIVED` → `CLEARED`, with a damage-hold loop hanging off `RECEIVED`. Dispatch (`action` `DISPATCH`, by the `Shipper`) is permitted only when the origin stop is `TEARDOWN` or `CLOSED` — or the origin is null for that first leg — and the four-clause coverage rule of §3.5 is satisfied for the leg. Dispatch physically commits the crates: every crate on the manifest moves from `AT_VENUE` (or `AT_ORIGIN`) to `IN_TRANSIT`, with each crate's `current_stop_id` pointed at the destination stop. Departure (`DEPART`, by the `Shipper`) walks the shipment `DISPATCHED` → `IN_TRANSIT`, and receipt (`RECEIVE`, by the `Registrar`) lands it at `RECEIVED`.

From `RECEIVED` there are two exits, one deliberate and one involuntary. Clearance (`CLEAR`, by the `Registrar`) requires that no damage claim on the shipment sits in `FILED`, `UNDER_REVIEW`, or `APPROVED`, and that every crate on the manifest carries an `ACCEPTED` report in the `UNPACK` phase; it lands the shipment in terminal `CLEARED`. The involuntary exit belongs to the system: the moment an `UNPACK` report on the shipment is submitted with a composite score below seventy, the shipment drops `RECEIVED` → `DAMAGE_HOLD`. While the hold stands, installation at the destination stop cannot begin. The hold releases — `DAMAGE_HOLD` → `RECEIVED` — only once every damage claim on the shipment has reached `PAID` or `DENIED`, and a shipment may cycle through the loop more than once.

### 3.7. Condition Inspection and Damage Claims

Condition reports are the registrar's instrument, filed one crate at a time against a shipment's manifest. Filing one takes the `crate_id` under inspection, the `inspector_name` of the registrar performing it, the `phase` — `UNPACK` at the destination or `PACK` at the origin — a `surface_score` and a `structural_score`, each an integer from 0 to 100, and a `seal_intact` flag recording whether the tamper seal held. A report naming a `crate_id` that is not on the shipment's manifest is refused with `ERR_CRATE_NOT_ON_SHIPMENT`. Reports are born `DRAFT`; they list per shipment with `crate_id`, `phase`, and `status` filters, and a flat collection spans shipments with `shipment_id` or `crate_id` filters.

Submitting a report (`action` `SUBMIT`, by the `Registrar`) is phase-gated: an `UNPACK` report submits only while its shipment is `RECEIVED` or `DAMAGE_HOLD`, and a `PACK` report submits only while the origin stop is `TEARDOWN` or `CLOSED`. Submission computes the report's `composite_score` and moves it `DRAFT` → `SUBMITTED`. The composite is a weighted blend — forty percent of the `surface_score` plus sixty percent of the `structural_score`, rounded half-up to a whole number — with one override: when `seal_intact` is false, the composite is capped at forty no matter how high the weighted blend ran. The two phases run the identical formula but serve different ends. An `UNPACK` composite landing below seventy is what drops the shipment into `DAMAGE_HOLD` (§3.6). A `PACK` composite is the baseline: at claim time it is compared against the same crate's prior `UNPACK` score to establish what transit did to the crate.

From `SUBMITTED`, acceptance (`ACCEPT`, by the `TourManager`) moves the report to terminal `ACCEPTED` and writes its `composite_score` onto the crate as the crate's new `condition_score`. The `Shipper` may instead dispute the finding (`DISPUTE`), moving `SUBMITTED` → `DISPUTED`; a disputed report is resolved only by manager override, the same `ACCEPT` act moving `DISPUTED` → `ACCEPTED` and updating the crate's `condition_score` in exactly the same way.

When transit hurts, a `Registrar` or a `TourManager` files a damage claim against the shipment, naming the `condition_report_id` that evidences the damage, the total `claimed_amount_cents`, and an itemized `line_items` array whose entries each carry a `description` and an `amount_cents`. The filing is refused with `ERR_CLAIM_AMOUNT_MISMATCH` (HTTP 422) when the itemization is empty or when the claimed total does not equal the sum of its line amounts. A claim is born `FILED`; claims list per shipment and through a flat collection, filterable by `status`, `shipment_id`, or `condition_report_id`.

Adjudication runs `FILED` → `UNDER_REVIEW` → `APPROVED` → `PAID`, with a denial exit off review. The `TourManager` opens review (`REVIEW`) only when the underpinning condition report is `SUBMITTED` or `ACCEPTED`. The `Insurer` then adjudicates. Approval (`APPROVE`) is capped by coverage: the `claimed_amount_cents` must not exceed the `coverage_cents` of an `ISSUED` or `ACTIVE` certificate covering the destination stop, or the claim is refused with `ERR_CLAIM_EXCEEDS_COVERAGE`. An approved claim gets its `assessed_payout_cents`: each line item's `amount_cents` is multiplied by eighty percent and rounded half-up to whole cents, those per-line figures are summed into a subtotal, and the payout is the lesser of that subtotal and ninety percent of the `claimed_amount_cents` — the cap itself rounded half-up to whole cents. Denial (`DENY`) instead sets `assessed_payout_cents` to zero. Payment (`PAY`, by the `Insurer`) moves an approved claim to `PAID`. Both denial and payment re-examine the shipment's damage hold with the same rule: once no claim on the shipment remains in `FILED`, `UNDER_REVIEW`, or `APPROVED`, a held shipment returns from `DAMAGE_HOLD` to `RECEIVED`. `PAID` and `DENIED` are the claim's terminal states.

### 3.8. On Site: Installation, Opening, Teardown, and Close

Installation is the stop's most heavily gated move: a `TourManager` begins install (`action` `BEGIN_INSTALL`), taking the stop `CONTRACTED` → `INSTALLING`. The transition's own preconditions bite first — the tour must be `BOOKING`, `ON_TOUR`, or `IN_REFURBISHMENT`, and the inbound shipment bound for this stop must be `RECEIVED` or `CLEARED`, so a shipment sitting in `DAMAGE_HOLD` stalls installation until its claims resolve; any failed precondition rejects the move with `ERR_INVALID_STATE`. Two business checks then fire in a fixed order. Insurance comes first: a certificate covering this stop and satisfying the four-clause rule of §3.5 against the inbound leg must exist, or the attempt fails with `ERR_NO_INSURANCE_COVERAGE`. Supervision comes second: when the stop's `supervision_required` flag is true, a supervisor must already be assigned (§3.2), or the attempt fails with `ERR_SUPERVISOR_REQUIRED`. When installation does begin, every crate on the inbound shipment moves `IN_TRANSIT` → `AT_VENUE` with its `current_stop_id` set to this stop — and if the tour was `BOOKING` or `IN_REFURBISHMENT`, the system lifts it to `ON_TOUR`, the first installation anywhere on the route being exactly what ends the booking posture.

Opening the doors (`OPEN_TO_PUBLIC`, moving `INSTALLING` → `OPEN`) requires that every crate on the inbound shipment carry an `ACCEPTED` report in the `UNPACK` phase — the gallery cannot open on uninspected crates. Teardown (`BEGIN_TEARDOWN`, moving `OPEN` → `TEARDOWN`) carries no further conditions beyond state. Should the venue need the exhibit back, `REOPEN` returns the stop `TEARDOWN` → `OPEN` — but only while the participation contract is not yet `FINALIZED`; once the contract has been finalized, the stop's commercial outcome is sealed and teardown cannot be aborted.

Closing (`CLOSE_STOP`, moving `TEARDOWN` → `CLOSED`) demands two things. Every crate on the stop must carry an `ACCEPTED` report in the `PACK` phase for the outbound shipment — or for the stop's own inventory if no outbound shipment exists yet. And the stop's `actual_attendance` must have been reported; closing without it fails with `ERR_ATTENDANCE_MISSING`. On close, the system finalizes the contract: the FINAL fee variant computed from `actual_attendance` supersedes the provisional figure and lands in `final_fee_cents`, and the tour's `total_billed_cents` is recomputed. A close may also tip the tour into refurbishment (§3.9).

Cancellation — a stop transition whose `action` is `CANCEL` — splits two ways. Cancelling a `TENTATIVE` stop is free: the stop goes to `CANCELLED`, and any non-finalized contract on it finalizes with `final_fee_cents` of zero. Cancelling a `CONTRACTED` stop is permitted only while no shipment bound for that destination sits in `DISPATCHED`, `IN_TRANSIT`, `RECEIVED`, or `DAMAGE_HOLD`; it exacts the FINAL_CANCEL penalty fee (§3.3), retires any marketing kit on the stop, and voids the stop's certificate. `CLOSED` and `CANCELLED` are the stop's terminal states.

### 3.9. Refurbishment Interludes, Retirement, and the Tour Ledger

When a stop closes, the system reads the calendar. If that stop is the latest `CLOSED` stop by `teardown_end`, if a next stop exists in `TENTATIVE` or `CONTRACTED`, and if the gap from the closed stop's `teardown_end` to the next stop's `install_start` is strictly more than the tour's `refurbishment_gap_days`, the tour slips `ON_TOUR` → `IN_REFURBISHMENT`, and every crate still `AT_VENUE` on the closed stop moves to `IN_REFURBISHMENT`. The interlude ends the moment the next stop begins installing: the tour returns `IN_REFURBISHMENT` → `ON_TOUR`, and every crate in refurbishment goes back to `IN_TRANSIT`, bound for the installing stop.

Retirement is the tour's deliberate end — a `TourManager` transition (`action` `RETIRE`) available from `BOOKING`, `ON_TOUR`, or `IN_REFURBISHMENT`, landing in the terminal `RETIRED`. Its gates layer. Regardless of posture, retirement is refused with `ERR_TOUR_NOT_RETIREABLE` while any stop remains in `CONTRACTED`, `INSTALLING`, `OPEN`, or `TEARDOWN`, or while any damage claim is still open in `FILED`, `UNDER_REVIEW`, or `APPROVED`. The per-posture preconditions refine this floor: from `BOOKING`, no stop may sit in `CONTRACTED`, `INSTALLING`, `OPEN`, or `TEARDOWN`; from `ON_TOUR`, no stop may sit in `INSTALLING`, `OPEN`, or `TEARDOWN`; from `IN_REFURBISHMENT`, every damage claim must be terminal in `PAID` or `DENIED` — and the tour-wide refusal above applies on top of each.

The retirement cascade is identical from all three postures. Every `TENTATIVE` stop is cancelled. Every non-terminal contract — `DRAFT`, `SENT`, or `SIGNED` alike — is finalized with its `final_fee_cents` deemed equal to its `provisional_fee_cents`, the provisional figure standing in as final on retirement. Every marketing kit still `PLANNED` or `PRODUCED` is retired. Every certificate still `ISSUED` or `ACTIVE` is voided. Retiring from `IN_REFURBISHMENT` adds one more sweep: all crates sitting in `IN_REFURBISHMENT` return to `AT_ORIGIN`.

Throughout the lifecycle, the tour's ledger reads back through its financial summary: `total_billed_cents` of final fees billed across all stops, `total_collected_cents` of payments applied to participation fees, `total_waived_cents` of sponsorship waivers granted at signature, and the derived `outstanding_cents` still to be collected.

## 4. Endpoint Definitions

Endpoints that create a brand-new resource — tours, venues, crates, stops, contracts, marketing kits, certificates, shipments, condition reports, damage claims, and supervisor assignments — answer `201 Created`. Reads, field updates, lifecycle transitions, the press-release marker, and the logical-clock capability answer `200 OK`. In the table below, "All roles" means all five roles named in §2.1. Request payloads, preconditions, computed values, and side effects are specified by the narratives in §2 and §3; this table is only the method-and-path index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/_clock/set_current_utc` | Set the server's logical clock (fixed startup default 2026-08-01T00:00:00Z; never wall-clock) | TourManager |
| POST   | `/tours` | Create a tour | TourManager |
| GET    | `/tours` | List tours (paginated) | All roles |
| GET    | `/tours/{id}` | Get a tour | All roles |
| POST   | `/tours/{id}/transition` | Tour lifecycle transition (OPEN_BOOKING, RETIRE) | TourManager |
| POST   | `/venues` | Register a venue | TourManager |
| GET    | `/venues/{id}` | Get a venue | All roles |
| POST   | `/tours/{id}/crates` | Register a crate in the tour inventory | TourManager |
| GET    | `/tours/{id}/crates` | List crates of a tour | All roles |
| GET    | `/tours/{id}/crates/{crateId}` | Get a crate | All roles |
| POST   | `/tours/{id}/stops` | Book a stop on the tour (OCC-guarded) | TourManager |
| GET    | `/tours/{id}/stops` | List stops of a tour | All roles |
| GET    | `/tours/{id}/stops/{stopId}` | Get a stop | All roles |
| PATCH  | `/tours/{id}/stops/{stopId}` | Update mutable stop fields (actual_attendance, projected_attendance while TENTATIVE) | TourManager, VenueRegistrar |
| POST   | `/tours/{id}/stops/{stopId}/transition` | Stop lifecycle transition (CANCEL, BEGIN_INSTALL, OPEN_TO_PUBLIC, BEGIN_TEARDOWN, REOPEN, CLOSE_STOP) | TourManager |
| POST   | `/tours/{id}/stops/{stopId}/assign-supervisor` | Assign an on-site installation supervisor | TourManager |
| POST   | `/tours/{id}/stops/{stopId}/contract` | Create the participation contract for a stop | TourManager |
| GET    | `/tours/{id}/stops/{stopId}/contract` | Get the contract(s) for a stop | All roles |
| POST   | `/tours/{id}/stops/{stopId}/contract/transition` | Contract transition (SEND, REVOKE, SIGN) | TourManager, VenueRegistrar |
| POST   | `/tours/{id}/stops/{stopId}/marketing-kit` | Create the marketing kit plan for a stop | TourManager |
| GET    | `/tours/{id}/stops/{stopId}/marketing-kit` | Get marketing kit(s) for a stop | All roles |
| POST   | `/tours/{id}/stops/{stopId}/marketing-kit/send-press-release` | Mark the press release issued to the venue | TourManager |
| POST   | `/tours/{id}/stops/{stopId}/marketing-kit/transition` | Marketing kit transition (PRODUCE, DELIVER) | TourManager |
| POST   | `/tours/{id}/certificates` | Issue an insurance certificate covering a stop | Insurer |
| GET    | `/tours/{id}/certificates` | List certificates of a tour | All roles |
| GET    | `/tours/{id}/certificates/{certId}` | Get a certificate | All roles |
| POST   | `/tours/{id}/shipments` | Plan a shipment leg between consecutive stops | Shipper, TourManager |
| GET    | `/tours/{id}/shipments` | List shipments of a tour | All roles |
| GET    | `/tours/{id}/shipments/{shipmentId}` | Get a shipment | All roles |
| POST   | `/tours/{id}/shipments/{shipmentId}/transition` | Shipment transition (DISPATCH, DEPART, RECEIVE, CLEAR) | Shipper, Registrar |
| POST   | `/tours/{id}/shipments/{shipmentId}/reports` | File a condition report on a crate in the shipment manifest | Registrar |
| GET    | `/tours/{id}/shipments/{shipmentId}/reports` | List condition reports of a shipment | All roles |
| POST   | `/tours/{id}/shipments/{shipmentId}/reports/{reportId}/transition` | Report transition (SUBMIT, ACCEPT, DISPUTE) | Registrar, Shipper, TourManager |
| POST   | `/tours/{id}/shipments/{shipmentId}/claims` | File a damage claim against a shipment | Registrar, TourManager |
| GET    | `/tours/{id}/shipments/{shipmentId}/claims` | List damage claims of a shipment | All roles |
| POST   | `/tours/{id}/shipments/{shipmentId}/claims/{claimId}/transition` | Claim transition (REVIEW, APPROVE, DENY, PAY) | TourManager, Insurer |
| GET    | `/tours/{id}/financial-summary` | Derived tour ledger totals | All roles |
| GET    | `/tours/stops/{stopId}` | Flat read of a TourStop by id | All roles |
| GET    | `/tours/stops` | Flat list of TourStops, filterable by tour_id / venue_id | All roles |
| GET    | `/tours/contracts/{contractId}` | Flat read of a ParticipationContract by id | All roles |
| GET    | `/tours/contracts` | Flat list of ParticipationContracts, filterable by tour_stop_id | All roles |
| GET    | `/tours/crates/{crateId}` | Flat read of a Crate by id | All roles |
| GET    | `/tours/crates` | Flat list of Crates, filterable by tour_id / current_stop_id | All roles |
| GET    | `/tours/shipments/{shipmentId}` | Flat read of a Shipment by id | All roles |
| GET    | `/tours/shipments` | Flat list of Shipments, filterable by tour_id / origin_stop_id / destination_stop_id | All roles |
| GET    | `/tours/reports/{reportId}` | Flat read of a ConditionReport by id | All roles |
| GET    | `/tours/reports` | Flat list of ConditionReports, filterable by shipment_id / crate_id | All roles |
| GET    | `/tours/claims/{claimId}` | Flat read of a DamageClaim by id | All roles |
| GET    | `/tours/claims` | Flat list of DamageClaims, filterable by shipment_id / condition_report_id | All roles |
| GET    | `/tours/marketing-kits/{kitId}` | Flat read of a MarketingKit by id | All roles |
| GET    | `/tours/marketing-kits` | Flat list of MarketingKits, filterable by tour_stop_id | All roles |
| GET    | `/tours/certificates/{certId}` | Flat read of an InsuranceCertificate by id | All roles |
| GET    | `/tours/certificates` | Flat list of InsuranceCertificates, filterable by tour_id / tour_stop_id | All roles |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them in §2 and §3; this table is only the identifier-to-status index.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_NO_INSURANCE_COVERAGE` | 409 Conflict |
| `ERR_SUPERVISOR_REQUIRED` | 409 Conflict |
| `ERR_VENUE_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_REFURBISHMENT_GAP_VIOLATED` | 409 Conflict |
| `ERR_WINDOW_MALFORMED` | 422 Unprocessable Entity |
| `ERR_SPONSORSHIP_OVER_CAP` | 409 Conflict |
| `ERR_DUPLICATE_CONTRACT` | 409 Conflict |
| `ERR_ROUTE_NOT_CONSECUTIVE` | 409 Conflict |
| `ERR_CRATE_NOT_ON_SHIPMENT` | 409 Conflict |
| `ERR_CLAIM_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CLAIM_EXCEEDS_COVERAGE` | 409 Conflict |
| `ERR_ATTENDANCE_MISSING` | 409 Conflict |
| `ERR_TOUR_NOT_RETIREABLE` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
