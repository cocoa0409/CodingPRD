# Concert Tour Routing & Advance API — Product Requirements Document

## 1. Introduction

Routing a multi-market concert tour is a negotiation conducted against the calendar. A tour manager must stitch together markets, venues, and drive days into a workable route; promoters must be held, countered, and committed before dates expire; venue representatives must clear the technical, hospitality, and immigration paperwork that turns a confirmed date into an advanceable one; and accountants must settle every night against box-office reality under strict segregation of duties. When any piece slips — a radius-clause conflict with a competing date, an advance section stuck in review, a crew drive that violates rest rules — the whole tour's posture must react immediately, gating the operations that would compound the problem.

This document specifies the Concert Tour Routing & Advance API, the system of record for that entire lifecycle. It covers tour setup and routing, the promoter hold/confirm workflow, advance packet exchange, ticket on-sale timing and marketing attribution, per-show budgeting, settlement with variance detection, and the compliance-hold machinery that freezes or restricts a tour when something is wrong. All monetary quantities are integer cents; all temporal reasoning runs against a controllable logical clock rather than the wall clock, so that expiry, on-sale, and rest-day behavior is deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contracts that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes five roles, spelled exactly as follows: `TourManager`, `Promoter`, `VenueRep`, `SettlementAccountant`, and `Any`.

- A `TourManager` owns the tour lifecycle end to end: creating the tour, markets, venues, routing legs, and shows; driving tour state transitions; responding to promoter counters; confirming, advancing, performing, and cancelling shows; submitting advance-packet sections; managing budget lines and marketing spends; opening and resolving compliance holds; and advancing the logical clock.
- A `Promoter` places, counters, accepts, rejects, and withdraws holds on a show, submits the settlement for a performed show, and pushes box-office ticket counts.
- A `VenueRep` approves or rejects individual advance-packet sections.
- A `SettlementAccountant` verifies and pays settlements, acting as the independent second pair of eyes segregated from the `Promoter`.
- `Any` is a read-only shared role: all list and get endpoints are available to any authenticated actor carrying a valid role header.

An attempt to perform an operation outside the caller's role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). For every role — `TourManager`, `Promoter`, `VenueRep`, `SettlementAccountant`, and `Any` alike — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server never compares it to any resource's `id`; it is used only for identity comparisons between two actors, such as the segregation-of-duties check at settlement verification, where the verifying `SettlementAccountant`'s `X-User-ID` must differ from the submitting `Promoter's` `X-User-ID`.

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

List endpoints accept two query parameters. `limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items from the start of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — Tour, Market, Venue, RoutingLeg, Show, PromoterHold, AdvancePacket, BudgetLine, MarketingSpend, Settlement, and ComplianceHold — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix, unique across the system.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer starting at creation and incrementing by one on every mutation, including mutations caused by cascading side effects from operations on related resources.

Any change to a resource — including recomputation of derived fields such as a tour's projected totals or a venue's booked calendar — counts as a mutation that refreshes `updated_at` and increments `version`. The AdvancePacket additionally maintains `packet_revision`, an integer that increments every time any of its three sections transitions, and it is `packet_revision` (not the packet's `version`) that guards advance-packet approval under optimistic concurrency.

### 2.5. The Logical Clock

All time-dependent behavior in the system — hold expiry, on-sale thresholds, rest-day rechecks, performed-date gating — reads a server-maintained **logical clock**, never the wall clock. At server startup, before any explicit adjustment, the logical clock reads exactly `2026-05-01T00:00:00Z` and must not fall back to wall-clock time. A `TourManager` advances the logical clock through an admin-only test-driving capability that accepts a `to_iso8601` timestamp and sets the current UTC instant to that value. Advancing the clock triggers three sweeps in its wake: the hold-expiry sweep over promoter holds still in `PENDING` or `COUNTERED`, the tour's automatic on-sale to in-progress crossing when the earliest confirmed show's on-sale moment is reached, and rest-day rechecks on locked routing legs.

### 2.6. Tour Posture and Compliance Gating

A tour carries a derived `posture` in addition to its lifecycle `status`, computed continuously from the tour's active compliance holds. When any `ACTIVE` ComplianceHold with `severity` of `CRITICAL` exists on the tour, the posture is `FROZEN`. When no `CRITICAL` hold is active but at least one `ACTIVE` hold of `severity` `STANDARD` exists, the posture is `RESTRICTED`. When no `ACTIVE` ComplianceHold remains at all, the posture returns to `OPEN`. These transitions are automatic: opening a hold recomputes posture immediately, and resolving one recomputes it again.

Posture is a gate, not a label. A `FROZEN` tour blocks every show confirm, show advance, settlement, and on-sale opening. A `RESTRICTED` tour blocks show confirmation and the tour-wide on-sale opening, while still permitting advance-packet edits and hold negotiation to continue. Each show likewise carries a derived `posture` of `OPEN` or `GATED`: a show is `GATED` whenever its tour's posture is anything other than `OPEN` or while any section of its advance packet is not yet `APPROVED`, and a `GATED` show cannot be confirmed, advanced, or settled. The show's posture opens again automatically once the tour is `OPEN` and every packet section has reached `APPROVED`.

### 2.7. Monetary Values, Units, and Rounding

All monetary amounts are represented as integer cents — fields such as `base_rent_cents`, `guarantee_cents`, `estimated_cents`, `spend_cents`, and the settlement's `box_office_gross_cents` are whole numbers of cents, never fractional. Wherever a calculation produces a fractional cent, the result is rounded **half up** to the nearest integer cent. Per-show projected amounts are rounded half-up to integer cents individually **before** any tour-level summation; the tour-level totals then add those integer-cent amounts directly, with no second rounding applied to the sum. Distances are whole miles, drive times are whole minutes rounded half-up, and all date arithmetic (exclusivity windows, on-sale lead) is performed in whole days against UTC midnights.

### 2.8. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency checks; each requires a non-optional expected-version field in the request body, and a mismatch with the parent's current value is rejected with HTTP 412. Endpoints not listed here take no version field.

- **Show confirmation** requires `expected_tour_version`, carrying the client's last observed `version` of the tour. If the tour's `version` has advanced since the client read it — for example because another show was just confirmed, which mutates the tour's posture, its projected totals, and the venue's booked calendar by cascade — the request is rejected with `ERR_STALE_TOUR_VERSION` (HTTP 412).
- **Countering a promoter hold** requires `expected_show_version`, the client's last observed `version` of the show. A mismatch — as when a different hold on the same show was just accepted, mutating the show's status and frozen capacity — is rejected with `ERR_STALE_SHOW_VERSION` (HTTP 412).
- **Approving an advance-packet section** requires `expected_packet_revision`, the client's last observed `packet_revision` of the packet. Because every section transition bumps `packet_revision`, a parallel approval or rejection on another section invalidates the client's view, and the approval is rejected with `ERR_STALE_PACKET_REVISION` (HTTP 412).

### 2.9. Nested Resource Retrieval and Flat Fetch Routes

Most resources live under a tour in a nested URL hierarchy, addressed by path identifiers `tourId`, `marketId`, `venueId`, `legId`, `showId`, `holdId`, `section`, `lineId`, `spendId`, `packetId`, and `settlementId`. For any request targeting a nested path, the server validates path parameters strictly left to right: the first identifier that does not resolve to an existing resource produces a 404 rejection with `ERR_NOT_FOUND`, and no later segment is examined. A request for a show under a non-existent tour therefore fails on the tour segment before the show is ever looked up.

So that every child resource remains reachable from its identifier alone, the API also exposes segment-anchored **flat fetch** routes — for example, fetching a market, venue, routing leg, show, hold, advance packet, budget line, marketing spend, settlement, or compliance hold directly by its id without threading the tour path — along with flat search routes that filter by foreign key. Flat searches accept query parameters drawn from `tour_id`, `market_id`, `venue_id`, `show_id`, `from_market_id`, and `to_market_id` depending on the resource, plus the standard `limit` and `offset`. Nested list endpoints support analogous filters: shows by `market_id`, `venue_id`, or `status`; holds and compliance holds by `status`; compliance holds additionally by `severity`; budget lines by `category`; marketing spends by `channel`; and venues by `market_id`.

### 2.10. Validation Order and Request Well-Formedness

When several checks could reject the same request, the server evaluates them in a fixed order so the surfaced error is deterministic. First, the presence and well-formedness of the two auth headers (a failure yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, role authorization for the attempted operation (`ERR_INSUFFICIENT_PERMISSIONS`). Third, left-to-right existence of every path parameter (`ERR_NOT_FOUND`). Fourth, referential integrity of any foreign keys supplied in the request body — each such reference must resolve within the same tour (`ERR_REFERENTIAL_INTEGRITY`, HTTP 422). Fifth, the optimistic-concurrency check where the endpoint is guarded (the relevant 412 stale-version error). Sixth, whether the target entity is in a permissible state for the requested transition (`ERR_INVALID_STATE`). Seventh, the tour posture gate (`ERR_POSTURE_NOT_OPEN` or `ERR_POSTURE_FROZEN`, as the operation dictates). Only then are the domain rules evaluated: venue availability, on-sale lead time, the radius-clause sweep, crew-rest enforcement, hold counter limits and expiry, advance-packet completeness, settlement variance, the budget cap, segregation of duties, and uniqueness constraints. Independently of this ordering, any request with a malformed body, a missing required field, or a wrong-typed value is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Standing Up a Tour: Windows, Markets, and Venues

A `TourManager` opens a new tour by supplying its `tour_name`, the headlining `artist_name`, and the routing window bounded by `window_start_date` and `window_end_date`. The window end must fall strictly after the window start; a tour whose dates do not satisfy this is rejected as malformed. A freshly created tour begins with `status` of `PLANNING` and `posture` of `OPEN`, and all four financial rollups — `projected_gross_cents`, `projected_cost_cents`, `settled_gross_cents`, and `settled_cost_cents` — start at zero.

With the shell in place, the manager stages the tour's geography. Each **Market** is registered with a `market_code` identifying the metro within the tour, a display `metro_name`, a two-letter ISO-3166 `country_code`, and the two numbers that drive radius-clause enforcement: `radius_miles`, the radius around the market centroid, and `exclusivity_window_days`, the number of days before and after a confirmed show during which competing shows inside the radius are forbidden. Each market also carries a `territory_rank`, the promoter's priority rank within the tour, where a lower number marks the stronger market; the rank must be unique within the tour, and a duplicate is rejected with `ERR_DUPLICATE_KEY`. Markets can be listed with `limit` and `offset`, fetched individually, or fetched flat by id and searched by `tour_id`.

Venues are attached to a market by supplying its `market_id`, which must resolve to a market belonging to the same tour or the create fails with `ERR_REFERENTIAL_INTEGRITY`. A venue record captures its `venue_name`, the sellable `capacity` (which must be greater than zero), the flat `base_rent_cents` charged per show date, the `curfew_local_time` in HH:MM local form, and `available_dates`, the array of ISO dates on which the venue can host. The venue's `booked_dates` array is system-maintained, accumulating the dates on which a confirmed-or-later show occupies the room. The combination of `market_id` and `venue_name` must be unique within the tour, with violations again rejected as `ERR_DUPLICATE_KEY`.

A staged tour leaves `PLANNING` for `ROUTING` when the manager starts routing — but only if the tour is still in `PLANNING` (otherwise `ERR_TOUR_NOT_PLANNING`) and at least one market and one venue exist under it (otherwise `ERR_TOUR_UNSTAGED`). Staging is therefore a hard prerequisite: no routing, no holds, and no shows can meaningfully proceed until the geography exists.

### 3.2. Routing Legs, Drive Time, and Crew Rest

Between markets, the manager lays down **RoutingLeg** records, each naming its `from_market_id` and `to_market_id`, the `travel_date` on which the move happens, the estimated `drive_miles`, and a `leg_index` giving the leg's sequence within the tour. The index must be unique per tour (`ERR_DUPLICATE_KEY`), and both market references must resolve within the same tour (`ERR_REFERENTIAL_INTEGRITY`). Legs can be listed and fetched under the tour, or fetched flat by id and searched by `tour_id`, `from_market_id`, or `to_market_id`.

Drive time is derived, not entered. The system assumes a fleet average speed of 55 miles per hour: a leg's `drive_minutes` is the drive distance multiplied by 60 and divided by 55, rounded half-up to a whole minute. Whenever that computed drive time is **strictly greater than** 480 minutes — eight hours behind the wheel — the leg's `crew_rest_required` flag is set to true; at exactly 480 minutes the flag remains false. Both derived fields are recomputed whenever a leg is created or its distance changes.

A new leg starts `PLANNED`. Locking it — the manager's commitment that the move will happen — requires the leg to still be `PLANNED` (`ERR_INVALID_STATE` otherwise) and passes two safety checks. First, anchoring: the origin and destination markets must each contain at least one `CONFIRMED` show, unless the leg is a non-production ferry leg, in which case the anchor requirement is waived; a leg that fails this is rejected with `ERR_LEG_UNANCHORED`. Second, rest: either `crew_rest_required` must be false, or a rest day must be scheduled between the leg and its adjacent locked legs; violations are rejected with `ERR_REST_VIOLATION`. Locking recalculates the tour's posture, and where a rest violation is admitted through manual override, a `STANDARD` ComplianceHold of `hold_kind` `REST_VIOLATION` may be opened in consequence. A `LOCKED` leg is marked complete once the logical clock has reached its `travel_date` — attempting completion earlier is rejected with `ERR_LEG_NOT_YET` — and a still-`PLANNED` leg may instead be cancelled outright. `COMPLETED` and `CANCELLED` are terminal. Advancing the logical clock re-runs the rest-day rechecks across locked legs.

### 3.3. Negotiating with Promoters: The Hold Workflow

Shows are born into negotiation. A `TourManager` creates a show by naming its `market_id` and `venue_id`, the `show_date`, the `on_sale_at` timestamp at which tickets go on sale, and the blended `avg_ticket_price_cents`. The show date must fall inside the tour's routing window and must appear in the venue's `available_dates`, and the on-sale moment must lead the performance by at least 14 days: measured from `on_sale_at` to the show date as a UTC midnight, the gap must be no less than fourteen days, with a gap of exactly fourteen days allowed. A date outside the window or not hostable by the venue is rejected with `ERR_VENUE_UNAVAILABLE`; insufficient on-sale lead is rejected with `ERR_ON_SALE_LEAD_VIOLATED`. A new show enters `HOLD_REQUESTED`, its derived `posture` is computed, and an **AdvancePacket** is auto-created alongside it with all three sections — `tech_rider_status`, `hospitality_status`, and `immigration_status` — in `PENDING`. Since a gated posture follows from any incomplete section, a new show is effectively `GATED` until its paperwork clears.

Against that show, a `Promoter` places a **PromoterHold** carrying the `promoter_name`, the offered `guarantee_cents`, and a `versus_pct` between 0 and 100 — the percentage of net the promoter will pay if it beats the guarantee. A fresh hold is `PENDING` with `counter_count` at zero and a `hold_expires_at` set exactly 72 hours after placement. The negotiation then proceeds as a bounded exchange:

- **Countering** is the promoter's move from `PENDING` to `COUNTERED`, submitting revised `guarantee_cents` and `versus_pct` together with `expected_show_version`. The hold must not have expired (the logical clock must still be earlier than `hold_expires_at`, else `ERR_HOLD_EXPIRED`), and the exchange is capped at three counter rounds — a fourth attempt is rejected with `ERR_COUNTER_LIMIT`. A successful counter increments `counter_count` by one, extends `hold_expires_at` by a further 24 hours, and increments the show's `version` by one.
- **Responding to a counter** is the manager's move from `COUNTERED` back to `PENDING`, again only while the hold is unexpired. The response carries an `accept_counter` flag: when true, the hold's terms are replaced by the countered `guarantee_cents` and `versus_pct`; when false, the original terms stand and the promoter may counter again.
- **Acceptance** by the promoter moves the hold to `ACCEPTED`. From `PENDING` this additionally requires the show to be in `HOLD_REQUESTED` or `HOLD_PLACED`; from `COUNTERED` the accepted terms are whatever the hold currently carries. Either path requires an unexpired hold. The first acceptance on a show moves it from `HOLD_REQUESTED` to `HOLD_PLACED`, freezes the show's `capacity` as a snapshot of the venue's `capacity` at that moment, recomputes `gross_potential_cents` as that frozen capacity multiplied by `avg_ticket_price_cents`, and updates the venue's `booked_dates` calendar to reflect the held date.
- **Rejection** moves a `PENDING` or `COUNTERED` hold to `REJECTED`. The show remains `HOLD_REQUESTED`, and a new hold may subsequently be placed against it.
- **Expiry** is the system's move: whenever the logical clock reaches `hold_expires_at` — at exactly the expiry instant the hold is expired, not one second earlier — a hold still in `PENDING` or `COUNTERED` becomes `EXPIRED`, releasing the venue date if it was soft-blocked. The expiry sweep runs on every state transition of a hold and on every advance of the logical clock.
- **Withdrawal** by the promoter is possible from `PENDING`, `COUNTERED`, or even `ACCEPTED`, but not once the show has reached `ADVANCED` or `PERFORMED`. Withdrawing an accepted hold reverts the show from `HOLD_PLACED` back to `HOLD_REQUESTED` and releases the show date from the venue's `booked_dates` if it had been added.

Holds can be listed for a show with an optional `status` filter, fetched individually, or fetched flat by id and searched by `show_id`.

### 3.4. Confirming Shows: The Venue Calendar, the Radius Clause, and the OCC Gate

Confirmation converts a held date into a committed performance, and it is the most heavily guarded transition in the system. A `TourManager` confirms a show that is in `HOLD_PLACED` — any other state is rejected with `ERR_INVALID_STATE` — supplying `expected_tour_version` so that a stale view of the tour is caught with `ERR_STALE_TOUR_VERSION` before anything else happens. The tour's posture must be `OPEN` (`ERR_POSTURE_NOT_OPEN`): because even a single active standard hold restricts the tour, confirmation is impossible while any compliance hold is outstanding. The venue must still be able to host the date — `show_date` present in `available_dates` and absent from `booked_dates` — or the confirm fails with `ERR_VENUE_UNAVAILABLE`. The on-sale lead must still be satisfiable from the present: the current logical clock plus fourteen days must not fall after the show date, or the confirm fails with `ERR_ON_SALE_LEAD_VIOLATED`.

The final gate is the **radius-clause sweep**. The system examines every other show on the same tour whose status is `CONFIRMED`, `ADVANCED`, `PERFORMED`, or `SETTLED` and whose market differs from the candidate's. A conflict exists when the distance between the two markets' centroids is no greater than the **smaller** of the two markets' `radius_miles`, **and** the absolute gap between the two show dates is no greater than the **smaller** of the two markets' `exclusivity_window_days`. The date boundary is half-open in the strict sense: a gap exactly equal to the smaller window **is** a conflict, while a gap one day beyond it is not. When the conflicting date sits exactly at that window edge, the conflict is graded `STANDARD`; when it falls strictly inside the window, the conflict is `CRITICAL`. A `CRITICAL` conflict rejects the confirmation outright with `ERR_RADIUS_CONFLICT`. A `STANDARD` conflict does not block the confirmation — instead the system opens a ComplianceHold of `hold_kind` `RADIUS_CONFLICT` and severity `STANDARD` scoped to the new show, which immediately drops the tour's posture to `RESTRICTED` and thereby blocks any further confirmations until it is resolved.

A successful confirmation moves the show to `CONFIRMED`, adds `show_date` to the venue's `booked_dates`, increments the tour's `version` by one, and recomputes the tour's projected totals with the show now inside the forward projection set. Cancellation remains available from `HOLD_REQUESTED`, `HOLD_PLACED`, or `CONFIRMED`; cancelling a confirmed show releases `show_date` from the venue's `booked_dates`, withdraws the attached promoter hold (an `ACCEPTED` hold becomes `WITHDRAWN`), resets every advance-packet section back to `PENDING`, and recalculates the tour's posture. `CANCELLED` is terminal.

### 3.5. The Advance Packet and the Day Sheet

Between confirmation and performance lies the advance: the exchange of the documents a venue needs to host the show. The packet attached to each show has three independently moving sections, addressed by the `section` path identifier as one of `tech_rider`, `hospitality`, or `immigration`, and tracked through `tech_rider_status`, `hospitality_status`, and `immigration_status`. A `TourManager` submits a section, moving it from `PENDING` to `SUBMITTED`; a `VenueRep` then approves it (`SUBMITTED` to `APPROVED`) or rejects it (`SUBMITTED` to `REJECTED`). A rejected section does not stay rejected — the system records the rejection and immediately returns the section to `PENDING` so it can be re-submitted. Every one of these transitions — submit, approve, and reject alike — increments the packet's `packet_revision` by one, and each approval or rejection re-evaluates the show's posture. Approval is concurrency-guarded: the `VenueRep` must supply `expected_packet_revision` matching the packet's current `packet_revision`, or the approval is rejected with `ERR_STALE_PACKET_REVISION`, since a parallel section may have just moved. The immigration section alone may rest in `NOT_REQUIRED` where no immigration filing applies; for it, `NOT_REQUIRED` satisfies completeness exactly as `APPROVED` does.

Advancing the show — the `CONFIRMED` to `ADVANCED` transition — requires every section `APPROVED` (or immigration `NOT_REQUIRED`); anything short is rejected with `ERR_ADVANCE_INCOMPLETE`. The tour's posture must be `OPEN` or `RESTRICTED`: a `FROZEN` tour rejects the advance with `ERR_POSTURE_FROZEN`. Advancing flips the packet's `daysheet_issued` to true — the flag is true exactly when all three sections are approved (or immigration not required) **and** the show is `ADVANCED` — and recomputes the tour's projections, applying the post-on-sale variant to any show whose `on_sale_at` the logical clock has reached.

The day sheet is exposed as a computed read over the show, returning its `show_id`, the `daysheet_issued` flag, the current `packet_revision`, and `budget_total_cents`, a rollup totaling the show's committed estimated costs. The packet itself can be fetched under its show, or fetched flat by id and searched by `show_id`.

### 3.6. On-Sale, Ticket Feeds, and Marketing Spend

Once at least one show is `CONFIRMED` and the tour's posture is `OPEN`, the manager opens the on-sale across the tour, moving it from `ROUTING` to `ON_SALE`. With no confirmed shows the open is rejected with `ERR_NO_CONFIRMED_SHOWS`; a restricted or frozen posture is rejected with `ERR_POSTURE_NOT_OPEN`. From there the tour hands itself to the calendar: when the logical clock reaches the earliest `on_sale_at` among `CONFIRMED` shows, the tour moves automatically from `ON_SALE` to `IN_PROGRESS`, and every confirmed show whose on-sale moment has arrived re-projects its economics under the post-on-sale variant described in §3.8.

While tickets sell, the promoter pushes cumulative counts by updating the show's `tickets_sold`. Each such update recomputes the show's projection whenever the logical clock has reached its `on_sale_at` — before that moment the projection does not depend on actual sales, so nothing moves.

Marketing runs alongside the on-sale. Each **MarketingSpend** records a `channel` — one of `RADIO`, `SOCIAL`, `OOH`, `PRINT`, or `INFLUENCER` — the `spend_cents` placed, the `flight_start_date` and `flight_end_date` bounding the flight, and `attributed_ticket_sales`, the count the box-office pixel credits to that channel. Each line's `cpa_cents` is its spend divided by its attributed sales, rounded half-up to a whole cent; a line with zero attributed sales has a null `cpa_cents`. The show-level blended cost per acquisition divides the raw sum of all `spend_cents` by the raw sum of all `attributed_ticket_sales`, again rounded half-up, and is null when no sales are attributed at all. The blended figure is always computed from those raw sums — never by averaging the individually rounded per-line values. Spends can be listed with an optional `channel` filter, fetched individually, or fetched flat by id and searched by `show_id`.

### 3.7. Performance, Settlement, and Segregation of Duties

A show can be marked performed only from `ADVANCED`, and only once the logical clock has reached the end of the show date in UTC — earlier attempts are rejected with `ERR_SHOW_NOT_YET`. Marking performed moves the show to `PERFORMED`, spawns its **Settlement** in `DRAFT`, and drops the show from the forward projection set.

Settlement is a three-step handoff between two different desks. First, the `Promoter` submits the night's numbers: `box_office_gross_cents`, `taxes_cents`, `facility_fees_cents`, and `promoter_expenses_cents`. Submission requires the settlement to be in `DRAFT` and the show to be `PERFORMED` (otherwise `ERR_SHOW_NOT_PERFORMED`), and it computes two derived quantities. The `artist_share_cents` pulls the guarantee and versus percentage from the accepted hold on the show: the net is the box-office gross minus taxes, minus facility fees, minus promoter expenses, floored at zero when expenses would drive it negative; the artist's share is then the **greater** of the guarantee and the net multiplied by `versus_pct` hundredths, rounded half-up to whole cents. When the percentage-of-net figure falls short of the guarantee, the guarantee floor pays; when it meets or exceeds the guarantee, the versus deal kicks in. The `variance_cents` measures reporting drift: the expected box office is `tickets_sold` multiplied by `avg_ticket_price_cents`, and the variance is the reported gross minus that expectation. The `variance_flag` grades the absolute difference — `MATERIAL` at 500,000 cents or more, `MINOR` at 50,000 cents or more but below the material line, and `NONE` below that. Both boundaries are inclusive: exactly 50,000 cents is `MINOR`, exactly 500,000 cents is `MATERIAL`.

Second, a `SettlementAccountant` verifies a `SUBMITTED` settlement. Three independent guards apply here. A `MATERIAL` variance blocks verification outright with `ERR_MATERIAL_VARIANCE`. The fiscal guard compares the sum of `actual_cents` across the show's committed budget lines against the tour's per-show budget cap; exceeding the cap is rejected with `ERR_BUDGET_OVERRUN` (HTTP 402). And segregation of duties is enforced by identity: the verifying accountant's `X-User-ID` must differ from the submitting promoter's `X-User-ID`, or the verification is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Third, once `VERIFIED`, an accountant pays the settlement, moving it to the terminal `PAID`. Payment cascades: the show moves from `PERFORMED` to `SETTLED`, the tour's settled totals absorb the show's settled gross and cost, and the forward projections recompute without it. A settlement can be fetched under its show, or fetched flat by id and searched by `show_id`.

Budget lines themselves are managed throughout the show's life. A **BudgetLine** carries a `category` — `VENUE_RENT`, `CREW`, `TRANSPORT`, `BACKLINE`, `MARKETING`, `HOSPITALITY`, `INSURANCE`, or `MISC` — a free-text `description`, an `estimated_cents` pre-show figure, and an `actual_cents` that stays null until settlement data exists. The `is_committed` flag is set at creation from the show's status and becomes true once the show is `CONFIRMED`, `ADVANCED`, `PERFORMED`, or `SETTLED`; committed lines are locked against casual edits, with changes tracked through variance. Updating a line's `estimated_cents` or `actual_cents` recomputes the show's projected cost. Lines can be listed with an optional `category` filter, fetched individually, or fetched flat by id and searched by `show_id`.

### 3.8. Tour Financials, Compliance Holds, and Closing the Books

The tour's headline economics are maintained as a **forward projection** over a defined input set: exactly those shows whose status is `CONFIRMED`, `ADVANCED`, `PERFORMED`, or `SETTLED` — shows still in hold states or cancelled never enter the set. The projection recomputes on four triggers: a show's confirmation, its advance, the logical clock crossing a show's on-sale moment, and a settlement payment. Each show in the set is projected under one of two variants, chosen by the clock. While the logical clock is still earlier than the show's `on_sale_at`, the pre-on-sale variant projects gross as the frozen `capacity` multiplied by `avg_ticket_price_cents` and then by a sellout factor of 0.65 — the house is assumed sixty-five percent sold — and projects cost as the sum of `estimated_cents` over the show's committed budget lines plus 350 cents of per-ticket variable cost for every seat of capacity. Once the clock reaches `on_sale_at`, the post-on-sale variant projects gross as the actual `tickets_sold` multiplied by `avg_ticket_price_cents`, plus the remaining unsold seats (capacity minus tickets sold) multiplied by `avg_ticket_price_cents` and then by a decay factor of 0.35, and projects cost as the same committed-estimate sum plus 350 cents per ticket actually sold. Each show's projected gross and projected cost is rounded half-up to integer cents **before** aggregation; the tour's `projected_gross_cents` and `projected_cost_cents` are then plain integer sums of those per-show figures with no second rounding. The settled side is simpler: `settled_gross_cents` and `settled_cost_cents` sum the settled amounts over exactly those shows whose settlement has reached `PAID`. A computed tour P&L read returns all four totals — projected gross, projected cost, settled gross, settled cost — side by side.

Compliance holds are the tour's immune system. Beyond the `RADIUS_CONFLICT` and `REST_VIOLATION` holds the system opens itself, a `TourManager` may open a manual hold naming a `hold_kind` — one of `RADIUS_CONFLICT`, `VENUE_DOUBLE_BOOK`, `REST_VIOLATION`, `BUDGET_OVERRUN`, or `ADVANCE_OVERDUE` — a `severity` of `STANDARD` or `CRITICAL`, an optional `related_show_id` to scope the hold to one show, and a free-text `reason`. A new hold is immediately `ACTIVE`, and its opening recomputes the tour's posture on the spot: one `CRITICAL` hold freezes the tour; standard holds restrict it. Resolving a hold moves it to `RESOLVED` and recomputes posture again, restoring `OPEN` only when no active holds remain. Holds can be listed with optional `status` and `severity` filters, fetched individually, or fetched flat by id and searched by `tour_id`.

The endgame is deliberately gated. Once every show on an `IN_PROGRESS` tour has reached `SETTLED` or `CANCELLED` — any show still pending blocks the move with `ERR_SHOWS_PENDING` — the manager moves the tour into `SETTLEMENT_REVIEW`. From there, closing the tour requires every settlement to be `PAID` (or its show `CANCELLED`), otherwise `ERR_SETTLEMENTS_OPEN`, and no `ACTIVE` compliance hold of any severity, otherwise `ERR_HOLDS_OUTSTANDING`. A close that passes both checks moves the tour to `CLOSED`, its terminal state, with the books complete.

## 4. Endpoint Definitions

All endpoints are mounted under the `/tours` prefix. Operations that create a new resource return `201 Created`; operations that read, modify, or transition an existing resource return `200 OK`. Request and response payloads for each endpoint are reconstructed from the workflows in §3; the table below is the routing contract only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/tours` | Create a tour | TourManager |
| GET | `/tours` | List tours (paginated) | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/{tourId}` | Get a tour | TourManager, Promoter, VenueRep, SettlementAccountant |
| POST | `/tours/{tourId}/start-routing` | Advance tour to ROUTING | TourManager |
| POST | `/tours/{tourId}/open-on-sale` | Open ticket on-sale across the tour | TourManager |
| POST | `/tours/{tourId}/enter-settlement-review` | Move tour into SETTLEMENT_REVIEW | TourManager |
| POST | `/tours/{tourId}/close` | Close tour | TourManager |
| POST | `/tours/{tourId}/markets` | Create a market | TourManager |
| GET | `/tours/{tourId}/markets` | List markets for a tour | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/{tourId}/markets/{marketId}` | Get a market | TourManager, Promoter, VenueRep, SettlementAccountant |
| POST | `/tours/{tourId}/venues` | Create a venue under a market | TourManager |
| GET | `/tours/{tourId}/venues` | List venues for a tour; optional market_id filter | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/{tourId}/venues/{venueId}` | Get a venue | TourManager, Promoter, VenueRep, SettlementAccountant |
| POST | `/tours/{tourId}/routing-legs` | Create a routing leg | TourManager |
| GET | `/tours/{tourId}/routing-legs` | List routing legs | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/{tourId}/routing-legs/{legId}` | Get a routing leg | TourManager, Promoter, VenueRep, SettlementAccountant |
| POST | `/tours/{tourId}/routing-legs/{legId}/lock` | Lock a routing leg | TourManager |
| POST | `/tours/{tourId}/routing-legs/{legId}/complete` | Complete a routing leg | TourManager |
| POST | `/tours/{tourId}/routing-legs/{legId}/cancel` | Cancel a routing leg | TourManager |
| POST | `/tours/{tourId}/shows` | Create a show (starts in HOLD_REQUESTED) | TourManager |
| GET | `/tours/{tourId}/shows` | List shows | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/{tourId}/shows/{showId}` | Get a show | TourManager, Promoter, VenueRep, SettlementAccountant |
| POST | `/tours/{tourId}/shows/{showId}/confirm` | Confirm a held show | TourManager |
| POST | `/tours/{tourId}/shows/{showId}/advance` | Advance a confirmed show | TourManager |
| POST | `/tours/{tourId}/shows/{showId}/mark-performed` | Mark an advanced show performed | TourManager |
| POST | `/tours/{tourId}/shows/{showId}/cancel` | Cancel a show | TourManager |
| PATCH | `/tours/{tourId}/shows/{showId}/tickets` | Box-office ticket sales update | Promoter |
| POST | `/tours/{tourId}/shows/{showId}/holds` | Place a hold (promoter) | Promoter |
| GET | `/tours/{tourId}/shows/{showId}/holds` | List holds for a show | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/{tourId}/shows/{showId}/holds/{holdId}` | Get a hold | TourManager, Promoter, VenueRep, SettlementAccountant |
| POST | `/tours/{tourId}/shows/{showId}/holds/{holdId}/counter` | Promoter counters a hold | Promoter |
| POST | `/tours/{tourId}/shows/{showId}/holds/{holdId}/respond-counter` | Tour manager responds to a counter | TourManager |
| POST | `/tours/{tourId}/shows/{showId}/holds/{holdId}/accept` | Promoter accepts the current hold terms | Promoter |
| POST | `/tours/{tourId}/shows/{showId}/holds/{holdId}/reject` | Promoter rejects | Promoter |
| POST | `/tours/{tourId}/shows/{showId}/holds/{holdId}/withdraw` | Promoter withdraws a hold | Promoter |
| GET | `/tours/{tourId}/shows/{showId}/advance-packet` | Get the advance packet for a show | TourManager, Promoter, VenueRep, SettlementAccountant |
| POST | `/tours/{tourId}/shows/{showId}/advance-packet/sections/{section}/submit` | Submit a section (tech_rider, hospitality, or immigration) | TourManager |
| POST | `/tours/{tourId}/shows/{showId}/advance-packet/sections/{section}/approve` | Approve a section | VenueRep |
| POST | `/tours/{tourId}/shows/{showId}/advance-packet/sections/{section}/reject` | Reject a section | VenueRep |
| POST | `/tours/{tourId}/shows/{showId}/budget-lines` | Add a budget line | TourManager |
| GET | `/tours/{tourId}/shows/{showId}/budget-lines` | List budget lines for a show | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/{tourId}/shows/{showId}/budget-lines/{lineId}` | Get a budget line | TourManager, Promoter, VenueRep, SettlementAccountant |
| PATCH | `/tours/{tourId}/shows/{showId}/budget-lines/{lineId}` | Update estimated_cents or actual_cents | TourManager |
| POST | `/tours/{tourId}/shows/{showId}/marketing-spends` | Create marketing spend | TourManager |
| GET | `/tours/{tourId}/shows/{showId}/marketing-spends` | List marketing spends for a show | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/{tourId}/shows/{showId}/marketing-spends/{spendId}` | Get a marketing spend | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/{tourId}/shows/{showId}/settlement` | Get settlement for a show | TourManager, Promoter, VenueRep, SettlementAccountant |
| POST | `/tours/{tourId}/shows/{showId}/settlement/submit` | Promoter submits settlement | Promoter |
| POST | `/tours/{tourId}/shows/{showId}/settlement/verify` | Accountant verifies settlement | SettlementAccountant |
| POST | `/tours/{tourId}/shows/{showId}/settlement/pay` | Accountant marks paid | SettlementAccountant |
| POST | `/tours/{tourId}/compliance-holds` | Open a manual compliance hold | TourManager |
| GET | `/tours/{tourId}/compliance-holds` | List compliance holds | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/{tourId}/compliance-holds/{holdId}` | Get a compliance hold | TourManager, Promoter, VenueRep, SettlementAccountant |
| POST | `/tours/{tourId}/compliance-holds/{holdId}/resolve` | Resolve a compliance hold | TourManager |
| GET | `/tours/markets/{marketId}` | Flat fetch of a Market by id | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/markets` | Flat search: markets by tour_id | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/venues/{venueId}` | Flat fetch of a Venue by id | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/venues` | Flat search: venues by tour_id and/or market_id | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/routing-legs/{legId}` | Flat fetch of a RoutingLeg by id | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/routing-legs` | Flat search: routing legs by tour_id, from_market_id, to_market_id | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/shows/{showId}` | Flat fetch of a Show by id | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/shows` | Flat search: shows by tour_id, market_id, venue_id | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/holds/{holdId}` | Flat fetch of a PromoterHold by id | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/holds` | Flat search: holds by show_id | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/advance-packets/{packetId}` | Flat fetch of an AdvancePacket by id | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/advance-packets` | Flat search: advance packets by show_id | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/budget-lines/{lineId}` | Flat fetch of a BudgetLine by id | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/budget-lines` | Flat search: budget lines by show_id | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/marketing-spends/{spendId}` | Flat fetch of a MarketingSpend by id | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/marketing-spends` | Flat search: marketing spends by show_id | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/settlements/{settlementId}` | Flat fetch of a Settlement by id | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/settlements` | Flat search: settlements by show_id | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/compliance-holds/{holdId}` | Flat fetch of a ComplianceHold by id | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/compliance-holds` | Flat search: compliance holds by tour_id | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/{tourId}/pnl` | Computed tour P&L: projected vs settled | TourManager, Promoter, VenueRep, SettlementAccountant |
| GET | `/tours/{tourId}/shows/{showId}/day-sheet` | Computed day sheet: show + packet + legs + budget rollup | TourManager, Promoter, VenueRep, SettlementAccountant |
| POST | `/_clock/set_current_utc` | Set the logical clock | TourManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_REFERENTIAL_INTEGRITY` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TOUR_NOT_PLANNING` | 409 |
| `ERR_TOUR_UNSTAGED` | 409 |
| `ERR_NO_CONFIRMED_SHOWS` | 409 |
| `ERR_POSTURE_NOT_OPEN` | 409 |
| `ERR_POSTURE_FROZEN` | 409 |
| `ERR_VENUE_UNAVAILABLE` | 409 |
| `ERR_ON_SALE_LEAD_VIOLATED` | 409 |
| `ERR_RADIUS_CONFLICT` | 409 |
| `ERR_REST_VIOLATION` | 409 |
| `ERR_LEG_UNANCHORED` | 409 |
| `ERR_LEG_NOT_YET` | 409 |
| `ERR_SHOW_NOT_PERFORMED` | 409 |
| `ERR_SHOW_NOT_YET` | 409 |
| `ERR_ADVANCE_INCOMPLETE` | 409 |
| `ERR_COUNTER_LIMIT` | 409 |
| `ERR_HOLD_EXPIRED` | 409 |
| `ERR_MATERIAL_VARIANCE` | 409 |
| `ERR_BUDGET_OVERRUN` | 402 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_DUPLICATE_KEY` | 409 |
| `ERR_SHOWS_PENDING` | 409 |
| `ERR_SETTLEMENTS_OPEN` | 409 |
| `ERR_HOLDS_OUTSTANDING` | 409 |
| `ERR_STALE_TOUR_VERSION` | 412 |
| `ERR_STALE_SHOW_VERSION` | 412 |
| `ERR_STALE_PACKET_REVISION` | 412 |
