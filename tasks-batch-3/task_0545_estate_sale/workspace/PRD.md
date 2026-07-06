# Estate Sale API — Product Requirements Document

## 1. Introduction

Companies in the estate-sale and senior-downsizing business (the "Caring Transitions" model) walk an estate through a long, financially sensitive arc: an initial home assessment and contract negotiation, the physical work of inventorying and researching each item, staging and tagging the home, running the sale itself with a point-of-sale register and, for the higher-value pieces, silent-auction bidding, and finally cleaning out whatever remains through donation or haul-away. The Estate Sale API exists to give the operators who run this business — managers, appraisers, cashiers, and the estate owners themselves — a single system of record that keeps the money honest from the first walk-through to the final settlement check.

The domain is fundamentally a ledger-reconciliation problem wrapped around a pricing engine. Every lot that sells, every card swipe that carries a processing fee, every cash advance the company fronts to a client for a buyout, and every crew hour booked against a sale window must reconcile into a settlement statement that the client can trust. Two independent pricing rules run in parallel — a time-decaying markdown schedule for fixed-price goods and a silent-auction resolution for bid lots — and both feed the same gross-sales figure. Because several of these operations mutate the same project's financial totals, the settlement step is guarded by optimistic concurrency so that a payout is never computed against a stale view of the estate.

This document specifies the complete contract: the resources, their lifecycles, the calculations that turn raw sales into a client payout, the validation and authorization rules that protect the process, and the exact API surface an implementation must expose.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes five roles, spelled exactly as follows: `PlatformAdmin`, `SaleManager`, `Appraiser`, `Cashier`, and `Client`.

Four of these roles carry an **opaque** identity. When `X-User-Role` is `PlatformAdmin`, `SaleManager`, `Appraiser`, or `Cashier`, the `X-User-ID` value is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it to any entity's `id`. The server may nonetheless record it: when an `Appraiser` runs the research step on a lot, their `X-User-ID` is stamped onto the lot as `researched_by_user_id`, and when a `SaleManager` approves a buyout, their `X-User-ID` is stamped as `approved_buyout_by_user_id`. These recorded identifiers drive the segregation-of-duties control described in §2.10 but are never treated as foreign keys to a user table.

The `Client` role carries an **entity-backed** identity. When `X-User-Role` is `Client`, the `X-User-ID` is the `id` of the acting `Client` entity; ownership checks on any project that references a client compare the project's `client_id` to `X-User-ID`. Concretely, the two project transitions a client may drive — countering the proposed terms and signing the contract — are permitted only on a project whose `client_id` equals the caller's `X-User-ID`. A client acting on someone else's project is rejected with `ERR_UNAUTHORIZED`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every resource in this system — clients, projects, lots, sale events, crews, transactions, bids, haul jobs, trucks, and settlement statements — carries a standard set of system-managed fields:

- `id`: a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at`: an ISO 8601 UTC timestamp, refreshed on every modification to the resource.
- `version`: an integer that starts at 1 and increments by one on every mutation of the resource.

The `version` field carries special weight on the `Project` entity, because it is the anchor of the settlement concurrency guard (§2.7). A project's `version` is incremented by one whenever a transaction is rung up, whenever a transaction is voided, whenever a buyout is approved, and when the settlement statement is finalized — because each of those operations recomputes a financial total on the project. Refreshing a derived counter on a project (for example `gross_sales_cents` after a sale) is itself a mutation that updates `updated_at` and increments `version`.

### 2.5. Monetary Values, Precision, and Rounding

All monetary amounts are integer cents. Fields such as `list_price_cents`, `reserve_price_cents`, `final_price_cents`, `commission_cents`, and `net_to_client_cents` are whole numbers of cents; no fractional cents are ever stored or returned.

Wherever a calculation produces a fractional cent, the result is rounded using the **round half up** method to the nearest whole cent. Two rounding disciplines matter and differ by rule: the tiered commission rounds **once** on the aggregated tier amounts, while the card-processing fee rounds **per transaction** and then sums the already-rounded amounts. These two policies are stated in full in §3.8; the distinction is deliberate because rounding-then-summing and summing-then-rounding disagree at half-cent boundaries.

Markdown discount fractions (`markdown_day1_pct`, `markdown_day2_pct`, `markdown_day3plus_pct`) are decimal fractions between 0 (inclusive) and 1 (exclusive) and preserve their input precision; they are multipliers, not currency.

### 2.6. The Logical Clock

Time-dependent behavior — the markdown day index and the temporal-overlap checks for crews and trucks — reads a server-maintained **logical clock** rather than wall-clock time. A `PlatformAdmin` sets the clock by supplying a `to_iso8601` instant. Until the clock is first set, it reads a startup default of `2026-05-01T00:00:00Z`; the server never falls back to wall-clock time. All "current time" references in this document mean the current value of this logical clock.

### 2.7. Optimistic Concurrency on Settlement

Finalizing a project's payout is the one operation protected by optimistic concurrency control. The settlement-create request must carry `expected_project_version`, a non-optional field holding the `Project.version` the caller last observed. If that value does not equal the project's current `version`, the request is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412), and no statement is created.

The reason is that a project's `version` advances every time a transaction is recorded or voided (each recompute of `gross_sales_cents` bumps it) and every time a prior settlement statement is created. If the caller last read the project before one of those writes landed, its observed snapshot of gross sales, buyout advances, and unsold counts would be out of date, and the computed payout would be wrong. Rejecting the stale create forces the caller to re-read the project and retry against its true current state. No other endpoint takes a version field.

### 2.8. Cascading Consistency and Derived Counters

Several project-level counters are **derived** and recomputed on write rather than supplied by clients: `gross_sales_cents`, `buyout_advances_cents`, `unsold_lot_count`, and the three estimate snapshots (`estimated_gross_consignment_cents`, `estimated_commission_cents`, `estimated_net_to_client_cents`). The exact recomputation rules live in §3, near the workflows that trigger them.

Some operations mutate more than one resource in a single atomic step; every such cascade must complete fully. Closing a sale event, cancelling a project, voiding a transaction, and resolving a bid lot all fan out to child resources. The full cascade specifications are stated in the §3 workflow that owns each operation, but the governing principle is uniform: when a parent operation changes a child's state, the child's own `updated_at` and `version` are refreshed, and any project counter that the change affects is recomputed immediately.

### 2.9. Referenced-Resource Resolution

Requests carry resource references both in the URL path (for example a `project_id`, `lot_id`, `sale_event_id`, `crew_id`, `transaction_id`, or `haul_job_id` path variable) and in request bodies (foreign keys such as `client_id`, `project_id`, `lot_id`, `sale_event_id`, `crew_id`, and `truck_id`). All such references are validated **left to right** — path identifiers first, then body foreign keys in the order they appear. The first reference that fails to resolve determines the error: an unresolved client yields `ERR_CLIENT_NOT_FOUND`, an unresolved project `ERR_PROJECT_NOT_FOUND`, an unresolved lot `ERR_LOT_NOT_FOUND`, an unresolved sale event `ERR_SALE_EVENT_NOT_FOUND`, an unresolved crew `ERR_CREW_NOT_FOUND`, an unresolved truck `ERR_TRUCK_NOT_FOUND`, an unresolved transaction `ERR_TRANSACTION_NOT_FOUND`, and an unresolved haul job `ERR_HAUL_JOB_NOT_FOUND` — all HTTP 404.

The system also exposes two reverse-reachability read paths so that children can be discovered from their parent: the bids placed on a given lot (a list keyed by the lot's `id`), and the settlement statements produced for a given project (a list keyed by the project's `id`).

### 2.10. Segregation of Duties

The operator who researched and priced a lot may not be the one who approves converting it to a company buyout. When a buyout is approved, the acting `SaleManager`'s `X-User-ID` is compared to the lot's `researched_by_user_id` (the `Appraiser` who ran the research step). If they are the same person, the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). This conflict-of-interest control ensures no single individual can both set a lot's value and authorize the company to buy it at that value.

### 2.11. Request Validation Order

When more than one thing is wrong with a request, the response reports the failure of highest priority. Checks are evaluated in this fixed order:

1. **Authentication** — both `X-User-ID` and `X-User-Role` headers present, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the acting role is permitted for the endpoint, and for a client-actor project transition the caller's `X-User-ID` equals the project's `client_id`, else `ERR_UNAUTHORIZED` (403).
3. **Body well-formedness** — required fields present, enum values in range, numeric fields at least 0, and a bid lot supplies its `bid_mode`, else `ERR_VALIDATION` (400).
4. **Existence** — path identifier and referenced foreign keys resolve, validated left to right, else the matching `ERR_*_NOT_FOUND` (404).
5. **Concurrency** — on settlement create, `expected_project_version` equals the project's current `version`, else `ERR_STALE_PROJECT_VERSION` (412).
6. **State** — the target resource is in a valid state for the requested transition, else the matching state error (409): `ERR_INVALID_STATE`, `ERR_PROJECT_TERMINAL`, `ERR_LOT_NOT_SELLABLE`, `ERR_SALE_NOT_OPEN`, `ERR_PROJECT_NOT_IN_SALE`, or `ERR_NOT_BID_LOT`.
7. **Segregation of duties** — on buyout approval, the acting `X-User-ID` differs from the lot's `researched_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES` (403).
8. **Temporal availability** — crew and truck booking windows are free, else `ERR_CREW_DOUBLE_BOOKED` or `ERR_TRUCK_UNAVAILABLE` (409).
9. **Booking constraints** — the sale window is not too long and a bid clears its minimums, else `ERR_SALE_WINDOW_TOO_LONG` or `ERR_BID_TOO_LOW` (422).
10. **Fiscal floor** — a fixed-price markdown does not fall below the lot's reserve, else `ERR_BELOW_RESERVE` (422).

## 3. Business Logic & Workflows

### 3.1. Client Intake, Assessment, and Contract Negotiation

Every engagement begins with a `Client` — the estate owner or downsizing senior — registered by a `PlatformAdmin` with a `name`, a `phone` number, and an optional `email` (absent by default). Against that client, a `PlatformAdmin` opens a `Project`, the top-level engagement, supplying the client's `client_id`, the estate `address`, the manager's rough `estimated_total_value_cents` from the walk-through, and optionally a `minimum_commission_cents` floor. That floor is the commission the company keeps regardless of how the tiered math turns out; when omitted it defaults to 50000 cents. A new project opens in the `LEAD` state with all of its derived counters — `gross_sales_cents`, `buyout_advances_cents`, `unsold_lot_count`, and the three estimate fields — initialized to zero.

The project then walks a negotiation arc, driven mostly by the `SaleManager`. From `LEAD` the manager records the home-assessment write-up, storing `assessment_notes` as the project advances `LEAD → ASSESSED`. From `ASSESSED` the manager puts terms on the table, advancing `ASSESSED → PROPOSED`; a `minimum_commission_cents` supplied on this step is recorded as the proposed floor. The project may also have its `address` corrected during these lifecycle updates. None of these transitions are permitted once the project is terminal; a mutation attempted on a `SETTLED` or `CANCELLED` project is rejected with `ERR_PROJECT_TERMINAL`.

Negotiation is a genuine loop. From `PROPOSED`, the `Client` may reject the current terms and counter, driving `PROPOSED → COUNTERED` — but only on their own project, where the caller's `X-User-ID` equals the project's `client_id`. The `SaleManager` then re-proposes, driving `COUNTERED → PROPOSED` and possibly adjusting `minimum_commission_cents`, and the two sides can cycle through `PROPOSED ↔ COUNTERED` as many times as needed. The loop closes when the `Client` signs: `PROPOSED → CONTRACTED`, again permitted only on the client's own project. Signing the contract is what unlocks lot creation. Any lifecycle transition requested from a state that does not offer it is rejected with `ERR_INVALID_STATE`.

### 3.2. Building the Inventory: Research, Pricing, Staging, and Listing

Once a project is `CONTRACTED`, an `Appraiser` begins cataloguing. Each item becomes a `Lot`, created against the project's `project_id` with a `title`. A lot defaults to `CONSIGNMENT` handling and to a fixed-price sale (`is_bid_lot` false); an appraiser may instead mark it a bid lot, in which case the `bid_mode` — `FIRST_PRICE` or `SECOND_PRICE` — is required. A lot may also be created with its `list_price_cents`, `reserve_price_cents`, and `min_increment_cents` if known, though these are more commonly filled in during pricing. A new lot opens in the `NEW` state. Note that `handling_type` can never be set to `BUYOUT` at creation — `BUYOUT` is reachable only through the buyout-approval step in §3.5.

The appraiser then walks each lot up a staging ladder. The research step, `NEW → RESEARCHED`, stores the comparable-sales `research_notes` and stamps the acting appraiser's `X-User-ID` onto the lot as `researched_by_user_id`; it is permitted only while the project's `status` is one of `CONTRACTED`, `SALE_SETUP`, or `SALE_LIVE`. Pricing, `RESEARCHED → PRICED`, requires that `list_price_cents` be present either from this call or a prior one. Staging (`PRICED → STAGED`) and tagging (`STAGED → TAGGED`) carry no preconditions. Listing, `TAGGED → LISTED`, is gated on the project having reached the sale phase: it is allowed only when the project's `status` is `SALE_SETUP` or `SALE_LIVE`, and a listing attempt against a project not yet in the sale is rejected with `ERR_PROJECT_NOT_IN_SALE`.

Pricing is revisable. From any of `PRICED`, `STAGED`, `TAGGED`, or `LISTED`, an appraiser may re-open a lot back to `RESEARCHED` to re-research and re-price it, provided the lot has not yet sold. This cyclic loop lets appraisers correct valuations right up until a sale. Along the way a lot's `list_price_cents`, `reserve_price_cents`, `min_increment_cents`, `research_notes`, and `bid_mode` can be adjusted. The `min_increment_cents` on a bid lot is the minimum a new bid must exceed the current high bid by; its role is detailed in §3.4.

### 3.3. Entering the Sale Phase: Estimate Snapshot, Sale Events, and Crews

When inventory is ready, the `SaleManager` moves the project `CONTRACTED → SALE_SETUP`. This transition takes a **forward-looking snapshot** of the expected result, freezing three numbers on the project. First, `estimated_gross_consignment_cents` is set to the sum of `list_price_cents` across all `CONSIGNMENT` lots that are then in one of the states `PRICED`, `STAGED`, `TAGGED`, or `LISTED`. Second, `estimated_commission_cents` is set to the tiered commission (the same tiered formula given in §3.8) computed over that estimated gross. Third, `estimated_net_to_client_cents` is set to the estimated gross consignment minus the estimated commission — with no card fees subtracted, because at snapshot time no card transactions have occurred yet. These estimates are computed once, at this transition, and are not recomputed as lots are later priced. From `SALE_SETUP` the manager advances the project to `SALE_LIVE`, then eventually to `SETTLING`.

Staffing the sale means booking a `Crew`. A crew is registered by a `PlatformAdmin` with a `name` and begins with `booked_minutes` at zero. The `SaleManager` schedules a `SaleEvent` against a project by supplying its `project_id`, the `crew_id` to staff it, and the sale window's `start_at` and `end_at` (ISO 8601 UTC, with `end_at` exclusive). The manager may override the default markdown schedule at this point; the three discount fractions are covered in §3.4. A new sale event opens in `SCHEDULED`.

Two guards apply when scheduling. The window may not be too long: its length, measured from `start_at` to `end_at`, must not exceed the maximum sale window of 4 days, and a longer window is rejected with `ERR_SALE_WINDOW_TOO_LONG`. And the crew must be free: the crew's booking is treated as the **half-open** interval from `start_at` up to but not including `end_at`, and if this interval overlaps any other `SCHEDULED` or `OPEN` sale event already booked on the same crew, the request is rejected with `ERR_CREW_DOUBLE_BOOKED`. On success the event's `window_minutes` is computed as the whole number of minutes in the window — the difference between `end_at` and `start_at` in seconds divided by 60, with any remainder discarded — and the crew's `booked_minutes` is recomputed as the sum of `window_minutes` across all of that crew's sale events currently in `SCHEDULED` or `OPEN` status. Cancelled and closed events do not count toward a crew's booked minutes.

### 3.4. Sale Day: Opening the Register, Markdowns, and Bidding

A sale goes live event by event. A `SaleManager` opens a scheduled event, driving `SCHEDULED → OPEN`, which is permitted only while the parent project's `status` is `SALE_LIVE`. The register is only live against an `OPEN` event.

**Fixed-price markdowns.** For a fixed-price lot (`is_bid_lot` false), the price a buyer pays decays over the sale window according to a day-indexed markdown schedule. The **day index** is the number of whole days elapsed since the event's `start_at`: take the current logical-clock time minus `start_at` in seconds, divide by the number of seconds in one day (86400), discard the fractional part, and clamp the result so it is never below zero. On day index 0 there is no discount. On day index 1 the discount fraction is `markdown_day1_pct` (default 0.25). On day index 2 it is `markdown_day2_pct` (default 0.50). On day index 3 or greater it is `markdown_day3plus_pct` (default 0.75). The realized price is the lot's `list_price_cents` multiplied by one minus the applicable discount fraction, rounded half up to whole cents.

**Silent-auction bidding.** For a bid lot, a `Cashier` records offers as `Bid` resources, each carrying the lot's `lot_id`, an `amount_cents`, and a `bidder_name`; a new bid opens in `PLACED`. A bid must clear two floors: its `amount_cents` must be at least the lot's `reserve_price_cents`, and it must be at least the current high bid plus the lot's `min_increment_cents`. A bid that fails either floor is rejected with `ERR_BID_TOO_LOW`. Bids may only be recorded against a bid lot; an attempt to bid on a fixed-price lot is rejected with `ERR_NOT_BID_LOT`.

When bidding is done, an `Appraiser` closes it. For a bid lot that has at least one `PLACED` bid, closing drives `LISTED → BID_CLOSED` and resolves the winner (§3.4 resolution below). For a bid lot with no `PLACED` bids at all, closing instead sends the lot straight to `UNSOLD` as an empty-set fallback, leaving `winning_bid_id` null and recomputing the project's `unsold_lot_count`. A close operation on a non-bid lot is rejected with `ERR_NOT_BID_LOT`.

**Winner resolution.** At close, the candidate bids are the `PLACED` bids whose `amount_cents` is at least the lot's `reserve_price_cents` (given the placement floors, this is every placed bid). Candidates are ordered by `amount_cents` descending, and ties are broken by `created_at` ascending so the earliest bid wins a tie. If no candidate qualifies, the lot goes `UNSOLD` and `winning_bid_id` stays null. Otherwise the first candidate is the winner: its `id` is stamped as the lot's `winning_bid_id`, that bid transitions `PLACED → WON`, and every other `PLACED` bid on the lot transitions `PLACED → LOST`. The price the winner pays, stamped as `winning_bid_price_cents`, depends on the lot's `bid_mode`:

- Under `FIRST_PRICE`, the winner pays their own high bid — the highest candidate `amount_cents`.
- Under `SECOND_PRICE`, if a second-highest candidate exists, the winner pays the smaller of their own high bid and the second-highest candidate's `amount_cents` plus the lot's `min_increment_cents`. If there is only one qualifying candidate, the winner pays the lot's `reserve_price_cents`.

**Ringing up the sale.** A `Cashier` records the sale of a lot as a `Transaction`, supplying the `sale_event_id` it rings up on, the `lot_id`, the `payment_method` (`CASH` or `CARD`), and an optional `buyer_name`. The transaction is only accepted while its sale event is `OPEN`; otherwise it is rejected with `ERR_SALE_NOT_OPEN`. The lot must be in a sellable state: a fixed-price lot must be `LISTED` and a bid lot must be `BID_CLOSED` with a `winning_bid_id` present, and any other case is rejected with `ERR_LOT_NOT_SELLABLE`. The transaction's `final_price_cents` is computed at ring-up: for a fixed-price lot it is the day-indexed markdown price described above, and for a bid lot it is the lot's `winning_bid_price_cents`. For a fixed-price lot the markdown price must not fall below the lot's `reserve_price_cents`; if it would, the sale is rejected with `ERR_BELOW_RESERVE`. On a successful ring-up the lot's own `final_price_cents` is stamped, the lot transitions to `SOLD`, the project's `gross_sales_cents` is recomputed, and the project's `version` is incremented by one. A new transaction opens in `RECORDED`.

Card sales carry a processing fee. A transaction's `card_fee_cents` is, for a `CARD` payment, the `final_price_cents` multiplied by 0.029 (the 2.9% card rate) rounded half up to whole cents, and it is 0 for a `CASH` payment.

### 3.5. Consignment versus Buyout

By default the company sells a lot on consignment and takes a commission at settlement. Alternatively, the company may buy a lot outright, paying the client an immediate cash advance and keeping any resale proceeds for itself. A `SaleManager` converts a lot by approving a buyout with a `buyout_price_cents` — the cash advance to the client. Approval flips the lot's `handling_type` to `BUYOUT`, stamps `buyout_price_cents` and the approving manager's `X-User-ID` as `approved_buyout_by_user_id`, adds the advance to the project's `buyout_advances_cents`, and increments the project's `version` by one. As stated in §2.10, the approving manager's `X-User-ID` must differ from the lot's `researched_by_user_id`, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`.

### 3.6. Voids and Closing the Sale

Mistakes at the register are corrected by a compensating void, performed by a `SaleManager`. A void is permitted only on a `RECORDED` transaction. It transitions the transaction `RECORDED → VOIDED`, returns the sold lot to the state it can sell from again — `LISTED` for a fixed-price lot or `BID_CLOSED` for a bid lot — clears the lot's `final_price_cents`, recomputes the project's `gross_sales_cents` (decrementing it by the voided amount), and increments the project's `version` by one.

At any point, `gross_sales_cents` is defined as the sum of `final_price_cents` over all of the project's transactions in `RECORDED` status — both consignment sales and buyout resales — so recording a sale and voiding one both simply re-derive that sum.

When a sale day ends, the `SaleManager` closes the event, driving `OPEN → CLOSED`. Closing cascades: every lot of that project still `LISTED` at close is moved to `UNSOLD`, the project's `unsold_lot_count` is recomputed as the count of the project's lots in `UNSOLD`, and the closed event's `window_minutes` is released from the crew's `booked_minutes`.

### 3.7. Cleanout: Haul Jobs and Trucks

Whatever does not sell is cleaned out. A `PlatformAdmin` registers a `Truck` by `name`. A `SaleManager` schedules a `HaulJob` against a project by supplying its `project_id`, the `truck_id`, a `disposition_type` (`DONATION`, `HAULAWAY`, or `BUYBACK`, the last returning items to the client), and the pickup window's `start_at` and `end_at`. A new haul job opens in `SCHEDULED`.

Truck availability is stricter than crew availability. A truck's pickup window is treated as the **closed** interval from `start_at` through `end_at` inclusive, and it additionally reserves a 60-minute buffer on each side for travel and turnaround. If the new job's window, expanded by that buffer, overlaps another `SCHEDULED` job on the same truck, the request is rejected with `ERR_TRUCK_UNAVAILABLE`. A `SaleManager` later completes a scheduled job (`SCHEDULED → COMPLETED`) or cancels it (`SCHEDULED → CANCELLED`).

### 3.8. Settlement and the Client Payout

Finalizing the payout is the last act. With the project moved to `SETTLING`, a `SaleManager` creates the `SettlementStatement` by supplying the `project_id` and the `expected_project_version` concurrency guard described in §2.7. A successful create computes the final figures, marks any prior statement for the same project as `superseded`, drives the project `SETTLING → SETTLED`, and increments the project's `version` by one.

The statement freezes six computed figures:

- `gross_consignment_cents`: the sum of `final_price_cents` over the project's `RECORDED` transactions whose lot's `handling_type` is `CONSIGNMENT`. Buyout resales are excluded, because their proceeds belong to the company, not the client.
- `commission_cents`: the tiered commission over `gross_consignment_cents`, floored by the guarantee. The tiered part is computed marginally: the portion of the consignment gross up to the first-tier threshold of 500000 cents is charged at the first-tier rate of 40 percent, and any portion above 500000 cents is charged at the second-tier rate of 30 percent; these two tier amounts are added together and that single aggregate sum is rounded half up to whole cents. The commission is then the larger of that rounded tiered amount and the project's `minimum_commission_cents`.
- `card_fees_cents`: the total card processing charged against consignment sales. For each `RECORDED` `CARD` transaction on a `CONSIGNMENT` lot, its individual fee is that transaction's `final_price_cents` multiplied by the 2.9% card rate, rounded half up to whole cents; these already-rounded per-transaction fees are then summed. The rounding happens per transaction and only then are the results summed — never the reverse.
- `buyout_advances_cents`: a copy of the project's `buyout_advances_cents` at settlement time, carried on the statement for information (the advances were already paid to the client at buyout approval).
- `net_to_client_cents`: `gross_consignment_cents` minus `commission_cents` minus `card_fees_cents`.
- `unsold_lot_count`: the count of the project's lots in `UNSOLD` at settlement time.

This is the **final** variant of the net-to-client calculation, computed post-sale from realized transactions. It parallels the **estimated** variant taken at the `SALE_SETUP` snapshot (§3.3): the estimate derives its gross from the sum of `list_price_cents` over `CONSIGNMENT` lots in `PRICED`, `STAGED`, `TAGGED`, or `LISTED`, and treats card fees as 0 since no card transactions have yet occurred, whereas the final derives its gross from realized `final_price_cents` over `RECORDED` consignment transactions and subtracts realized card fees. Both variants otherwise share the same net-to-client shape — gross consignment minus commission minus card fees.

### 3.9. Cancellation and Its Cascade

A `SaleManager` may cancel a project from any non-terminal state, driving it to `CANCELLED`; a cancel attempted on an already-terminal project is rejected with `ERR_PROJECT_TERMINAL`. Cancellation fans out through three linked cascades that all complete atomically. First, every non-terminal `Lot` of the project is moved to `WITHDRAWN`. Second, for each lot just withdrawn, its `PLACED` bids are moved to `VOIDED`. Third, every `SCHEDULED` or `OPEN` `SaleEvent` of the project is moved to `CANCELLED`, and each cancelled event's `window_minutes` is released from its crew's `booked_minutes`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify or transition an existing resource, including cancel, void, close, approve-buyout, and settlement-driven lifecycle changes, return `200 OK` — except creating a settlement statement, which mints a new `SettlementStatement` resource and therefore returns `201 Created`. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |
| POST | `/estate/clients` | Register an estate-owner client | PlatformAdmin |
| POST | `/estate/projects` | Open a project (home-assessment lead) | PlatformAdmin |
| GET | `/estate/projects/{project_id}` | Get a project | PlatformAdmin, SaleManager, Appraiser, Cashier, Client |
| GET | `/estate/projects` | List/filter projects | PlatformAdmin, SaleManager, Appraiser, Cashier, Client |
| PATCH | `/estate/projects/{project_id}` | Advance lifecycle / negotiation / assessment | SaleManager, Client |
| POST | `/estate/projects/{project_id}/cancel` | Cancel a project (cascades) | SaleManager |
| GET | `/estate/projects/{id}/settlement-statements` | List a project's settlement statements | PlatformAdmin, SaleManager, Client |
| POST | `/estate/lots` | Add a lot to a contracted project | Appraiser |
| GET | `/estate/lots/{lot_id}` | Get a lot | PlatformAdmin, SaleManager, Appraiser, Cashier, Client |
| GET | `/estate/lots` | List/filter lots | PlatformAdmin, SaleManager, Appraiser, Cashier, Client |
| PATCH | `/estate/lots/{lot_id}` | Research/price/stage/tag/list/re-research/close bidding | Appraiser |
| POST | `/estate/lots/{lot_id}/approve-buyout` | Convert a consignment lot to a buyout | SaleManager |
| GET | `/estate/lots/{id}/bids` | List bids on a lot | PlatformAdmin, SaleManager, Appraiser, Cashier |
| POST | `/estate/sale-events` | Schedule a sale event and book a crew | SaleManager |
| GET | `/estate/sale-events/{sale_event_id}` | Get a sale event | PlatformAdmin, SaleManager, Appraiser, Cashier, Client |
| GET | `/estate/sale-events` | List/filter sale events | PlatformAdmin, SaleManager, Appraiser, Cashier, Client |
| PATCH | `/estate/sale-events/{sale_event_id}` | Open a scheduled sale event | SaleManager |
| POST | `/estate/sale-events/{sale_event_id}/close` | Close a sale event (cascades unsold lots) | SaleManager |
| POST | `/estate/crews` | Register a staffing crew | PlatformAdmin |
| GET | `/estate/crews/{crew_id}` | Get a crew (exposes booked_minutes) | PlatformAdmin, SaleManager, Appraiser, Cashier |
| POST | `/estate/transactions` | Ring up a sale on an open sale day | Cashier |
| GET | `/estate/transactions/{transaction_id}` | Get a transaction | PlatformAdmin, SaleManager, Cashier |
| GET | `/estate/transactions` | List/filter transactions | PlatformAdmin, SaleManager, Cashier |
| POST | `/estate/transactions/{transaction_id}/void` | Void a POS sale (compensating reversal) | SaleManager |
| POST | `/estate/bids` | Place a silent-auction bid on a listed bid lot | Cashier |
| POST | `/estate/haul-jobs` | Schedule a cleanout/donation/haul-away and book a truck | SaleManager |
| GET | `/estate/haul-jobs/{haul_job_id}` | Get a haul job | PlatformAdmin, SaleManager, Client |
| GET | `/estate/haul-jobs` | List/filter haul jobs | PlatformAdmin, SaleManager, Client |
| PATCH | `/estate/haul-jobs/{haul_job_id}` | Complete or cancel a haul job | SaleManager |
| POST | `/estate/trucks` | Register a haul-away truck | PlatformAdmin |
| POST | `/estate/settlement-statements` | Finalize the payout and settle the project | SaleManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_CLIENT_NOT_FOUND` | 404 |
| `ERR_PROJECT_NOT_FOUND` | 404 |
| `ERR_LOT_NOT_FOUND` | 404 |
| `ERR_SALE_EVENT_NOT_FOUND` | 404 |
| `ERR_CREW_NOT_FOUND` | 404 |
| `ERR_TRUCK_NOT_FOUND` | 404 |
| `ERR_TRANSACTION_NOT_FOUND` | 404 |
| `ERR_HAUL_JOB_NOT_FOUND` | 404 |
| `ERR_STALE_PROJECT_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PROJECT_TERMINAL` | 409 |
| `ERR_LOT_NOT_SELLABLE` | 409 |
| `ERR_SALE_NOT_OPEN` | 409 |
| `ERR_PROJECT_NOT_IN_SALE` | 409 |
| `ERR_NOT_BID_LOT` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_CREW_DOUBLE_BOOKED` | 409 |
| `ERR_TRUCK_UNAVAILABLE` | 409 |
| `ERR_SALE_WINDOW_TOO_LONG` | 422 |
| `ERR_BID_TOO_LOW` | 422 |
| `ERR_BELOW_RESERVE` | 422 |
