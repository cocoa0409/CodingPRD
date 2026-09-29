# Comics Direct Market Publishing API — Product Requirements Document

## 1. Introduction

A comic book publisher lives or dies by two calendars that refuse to agree with each other. The editorial calendar is governed by human hands — a script arrives late, pencils get kicked back, a colorist needs another week — while the commercial calendar is governed by the direct market, where solicitation copy and cover images must be printed in a distributor catalog months before a book exists, retailers place firm non-returnable orders against that catalog, and a final order cut-off freezes the order book into a print bill that cannot be unwound. When the two calendars diverge, the damage is not editorial but financial: covers already promised, incentive tiers already earned, invoices already raised against retailer credit limits.

This document specifies the service that keeps both calendars in one system of record. It covers title greenlight and creative-team negotiation with page rates, royalty shares and recoupable advances; the production board of script, pencils, inks, colors and letters stages with lateness measurement and slip cascades; catalog solicitation with slot caps and submission deadlines; retailer order collection with ratio-incentive and retailer-exclusive variant covers; print-run sizing from either the locked order book or trailing demand; direct-market invoicing at volume discount tiers under non-returnable terms; digital and collected-edition scheduling with cannibalization blackouts; and creator royalty accounting across print, digital, collected and subsidiary channels with advance recoupment and reversible statements.

Every resource is mounted under the `/comics` prefix, and every temporal rule reads a single server-side logical clock rather than wall-clock time, so that a full publishing year can be exercised deterministically. The service is a strict ledger system: derived counters are always recomputed from their source rows rather than nudged by deltas, and every destructive action has an exact compensating action that restores the ledgers it touched.

## 2. Global Specifications & System-Wide Principles

### 2.1. Publishing Roles and Identity Headers

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role that user is acting in. If either header is absent, or if `X-User-Role` is not one of the six declared roles, the request is rejected with `ERR_UNAUTHENTICATED`. If the header pair is well formed but the named role does not appear in the authorized-role list for the requested endpoint (see §4), the request is rejected with `ERR_UNAUTHORIZED`.

The six roles are `EditorInChief`, `ManagingEditor`, `SalesDirector`, `RoyaltyAccountant`, `Creator` and `Retailer`. Duties are deliberately segregated: `EditorInChief` owns the title portfolio and the creative-terms surface, `ManagingEditor` owns the issue slate and the production board, `SalesDirector` owns the entire commercial surface (catalogs, covers, retailer accounts, the order cut-off, invoicing, shipping and release), and `RoyaltyAccountant` owns the money-out surface (revenue events and royalty statements). No role may perform another's exclusive work.

Four of the roles carry opaque identities. When `X-User-Role` is `EditorInChief`, `ManagingEditor`, `SalesDirector` or `RoyaltyAccountant`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it — it stores the issuing operator's identifier as `issued_by_user_id` and the paying operator's identifier as `paid_by_user_id` on a royalty statement — but it never compares such an identifier to any entity's `id`.

The remaining two roles are entity-backed. When `X-User-Role` is `Creator`, `X-User-ID` is the `id` of the acting `Creator` record; ownership checks on any resource that references a `Creator` compare that resource's `creator_id` to `X-User-ID`, and for a production stage the comparison is made against the `creator_id` of the assignment the stage was booked under. When `X-User-Role` is `Retailer`, `X-User-ID` is the `id` of the acting `Retailer` record; ownership checks on any resource that references a `Retailer` compare that resource's `retailer_id` to `X-User-ID`. An entity-backed identity acting on a resource it does not own is rejected with `ERR_FORBIDDEN_RESOURCE`. This ownership check guards exactly eight operations: countering an assignment, accepting an assignment, starting a production stage, delivering a production stage, drafting a retailer order (where the body's `retailer_id` must itself equal `X-User-ID`), submitting an order, adjusting an order, and cancelling an order.

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

Every list endpoint accepts two query parameters. The `limit` parameter caps the number of rows returned; when omitted it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. The `offset` parameter skips that many rows before the page begins; when omitted it defaults to 0, and its minimum accepted value is 0. A `limit` outside the range of 1 through 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST`.

Unless a subsection states otherwise, list endpoints return rows sorted by their creation timestamp in ascending order.

List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` states whether further rows exist beyond the current page.

### 2.4. The Logical Publishing Clock

Because solicitation deadlines, final order cut-offs, on-sale dates, embargoes and blackout windows all depend on "now", the service reads a single logical UTC clock rather than the host wall clock. An administrative capability at `/_clock/set_current_utc`, available to all six roles, sets that clock from a `to_iso8601` instant supplied in the request body and echoes the value back. Until it is ever called, the logical clock reads `2026-08-01T00:00:00Z`. Every temporal validation, every system-stamped timestamp (`greenlit_at`, `submitted_at`, `published_at`, `actual_delivered_at`, `printed_at`, `on_sale_date`) and the accounting period derived at shipment all read this clock.

Two date conventions apply throughout. Fields documented as dates — `booking_start_date`, `booking_end_date`, `target_on_sale_date`, `foc_date`, `planned_start_date`, `planned_due_date`, `release_date` — are supplied and stored as instants at midnight UTC. Whenever the specification speaks of a difference in calendar days, both operands are first truncated to their UTC calendar date and the difference is then taken in whole days; no partial days ever survive the arithmetic.

### 2.5. Record Identity, Timestamps and Row Versioning

Most resources in this system — creators, titles, creative assignments, issues, production stages, catalogs, solicitations, retailers, retailer orders, print runs and royalty statements — carry the same four system-managed properties:

- `id` (string): a server-minted UUID, with no type prefix of any kind.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, stamped when the row is first written.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the row, including mutations caused by a cascade or by a recomputation of a derived counter.
- `version` (integer): a counter that starts at 1 and increments by one on every mutation of the row, again including cascade-driven and recomputation-driven mutations.

Three record types are immutable once written and therefore carry only `id` and `created_at`: a variant cover, a release window and a revenue event. For those three, both `updated_at` and `version` are absent from the resource entirely.

### 2.6. Derived Status, Roll-Up Counters and Cascade Propagation

A large part of this system's state is not written by clients at all but derived from child rows, and the derivation is always a **full recompute over the qualifying child set**, never an incremental delta. An issue's production dimension is re-derived from the statuses of its production stages after every change to that stage set; a retailer's cumulative units and open balance are re-summed from that retailer's orders; an issue's ordered, printed and shipped unit counters are re-summed from its orders and print runs; a catalog's accepted slot count is re-counted from its solicitations; a title's committed royalty share, production cost and accrued royalty are re-summed from its assignments, stages and statements respectively. A consequence worth stating plainly: because these are recomputes rather than accumulations, a derived counter can move **downwards** when a contributing row leaves the qualifying set.

Cascades run inside the request that triggered them, in hop order, and each hop's inputs are the results of the previous hop. Three operations carry multi-hop cascades and are specified hop by hop in §3: delivering a production stage (slip measurement, then solicitation withdrawal, then order cancellation, then retailer ledger refresh), locking a final order cut-off (allocation freeze, then retailer tier refresh, then issue roll-up), and cancelling a title (assignment termination and issue cancellation, then child cancellation, then retailer and issue ledger refresh).

Some transitions bubble upwards instead. A title's own lifecycle is partly a function of its issues: the title leaves `GREENLIT` for `IN_PRODUCTION` when its first issue is created, leaves `IN_PRODUCTION` for `PUBLISHING` when its first issue goes on sale, and leaves `PUBLISHING` for `COMPLETED` when the count of its on-sale issues reaches its planned issue count. Every one of these server-initiated transitions is a mutation in the sense of §2.5: it refreshes the affected row's `updated_at` and increments that row's `version`, with no client request naming that row.

### 2.7. Ledger Discipline and Exact Compensation

Four ledgers are maintained as pure functions of their source rows, and their qualifying-status filters are the whole of their definition.

A retailer's `cumulative_units_ytd` equals that retailer's `opening_units_ytd` plus the sum of `total_units` over that retailer's orders whose status is `FOC_LOCKED`, `INVOICED` or `SHIPPED`. A retailer's `open_balance_cents` equals the sum of `invoice_total_cents` over that retailer's orders whose status is `INVOICED` or `SHIPPED`. An issue's `total_ordered_units` equals the sum of `total_units` over that issue's orders whose status is `FOC_LOCKED`, `INVOICED` or `SHIPPED`; its `shipped_units` equals the same sum restricted to orders whose status is `SHIPPED`; and its `printed_units` equals the sum of `quantity` over that issue's print runs whose status is `PRINTED`. Orders in `DRAFT`, `SUBMITTED` or `CANCELLED` contribute nothing to any of these figures, which is exactly what makes order cancellation an exact compensating action rather than an approximate one.

A title's `royalty_accrued_cents` equals the sum of `payable_cents` over that title's royalty statements whose status is `ISSUED` or `PAID`. An assignment's `unrecouped_advance_cents` equals that assignment's `advance_cents` minus the sum of `recoupment_applied_cents` over the statements for the same creator and the same title whose status is `ISSUED` or `PAID`. A `DRAFT` statement has not yet reached the ledger and a `REVERSED` statement has left it, which is what makes statement reversal restore the pre-issue figures exactly. A title's `production_cost_cents` equals the sum of `page_fee_cents` over the production stages whose status is `APPROVED` on that title's issues; because an approved stage is terminal and is never cancelled, this ledger only ever grows. A catalog's `accepted_slot_count` equals the count of that catalog's solicitations whose status is `ACCEPTED`; `DRAFT`, `SUBMITTED` and `WITHDRAWN` rows never occupy a slot.

### 2.8. Money, Units, Basis Points and Rounding

All monetary amounts in this system are integer counts of cents and are never fractional; a field named with a `_cents` suffix holds cents, and a field named with a `_bps` suffix holds basis points, where 10000 basis points is the whole. All unit, copy, page and day counts are likewise integers. Because every stored figure is already integral, rounding only ever appears inside a calculation, and each calculation names its own rounding rule and the point at which it is applied. Three rounding vocabularies are used and must not be substituted for one another: **round half up** (ties away from zero) for invoice lines and for the reprint demand projection; **floor** (truncate towards zero) for slip days, for incentive-cover earning, for returns reserve, for channel pools and for royalty shares; and **ceiling** (round up to the next whole unit) for print overprint and for carton rounding. Where a calculation prescribes an evaluation order — rounding each line before summing rather than summing before rounding, or striking a cover participation before normalising the remainder — that order is part of the contract and a different order producing a different cent total is a defect, not a variant.

### 2.9. Stale-Parent Protection on Roster and Printing Writes

Two creation operations write a child row whose correctness depends on a parent figure the client must have observed first, and neither can be protected by a state precondition because a repeat of the same operation is entirely legitimate. Both therefore require an explicit optimistic-concurrency field, and in both cases the field is a required input, not an optional one.

Creating a creative assignment under a title requires `expected_title_version` in the request body, carrying the client's last observed `version` of that `Title`. If that number does not equal the title's current `version`, the request is rejected with `ERR_STALE_TITLE_VERSION` and HTTP 412. A title legitimately accepts several assignments for the same craft — co-writers, fill-in artists — and every acceptance moves `committed_share_bps`, so no state check can catch a client that is budgeting a royalty share against a roster it has not seen. The stale-version check is what protects the royalty pool.

Creating a print run under an issue requires `expected_issue_version` in the request body, carrying the client's last observed `version` of that `Issue`. If that number does not equal the issue's current `version`, the request is rejected with `ERR_STALE_ISSUE_VERSION` and HTTP 412. Second printings and reprints legitimately stack on top of earlier runs, so a repeat creation is not blocked by state; the stale-version check ensures the ordering figures the run quantity is derived from are the ones the client actually observed.

No other endpoint accepts a version field, and no other endpoint performs a version comparison.

### 2.10. Path Resolution and the Order of Request Checks

When an endpoint path contains more than one resource identifier, the service resolves them strictly left to right and fails on the first one that does not exist: a title is resolved before an issue nested under it, and an issue before a stage, cover, print run, release window or solicitation nested under it. Each identifier has its own 404 code — `ERR_TITLE_NOT_FOUND`, `ERR_ISSUE_NOT_FOUND`, `ERR_CREATOR_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_STAGE_NOT_FOUND`, `ERR_CATALOG_NOT_FOUND`, `ERR_SOLICITATION_NOT_FOUND`, `ERR_RETAILER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_PRINT_RUN_NOT_FOUND` and `ERR_STATEMENT_NOT_FOUND` — and the code reported is the one belonging to the leftmost missing segment.

Beyond path resolution, several checks may be applicable to the same request, and the order in which they are evaluated is part of the contract, because it decides which error a client sees. Checks are evaluated in the following sequence, and the first failure ends the request:

1. **Authentication.** Both identity headers present and `X-User-Role` one of the six declared roles, otherwise `ERR_UNAUTHENTICATED` (401).
2. **Role authorization.** The acting role appears in the endpoint's authorized-role list in §4, otherwise `ERR_UNAUTHORIZED` (403).
3. **Request shape.** Required fields present, types correct, enum members legal, integers inside their declared ranges, `YYYY-MM` month strings well formed, `booking_end_date` strictly after `booking_start_date`, `planned_due_date` on or after `planned_start_date`, `on_sale_month` strictly after `solicitation_month`, `net_receipts_cents` no greater than `gross_receipts_cents`, `limit` between 1 and 100 and `offset` not negative — otherwise `ERR_INVALID_REQUEST` (400).
4. **Path existence,** resolved left to right as described above, with the 404 codes listed above.
5. **Body-referenced existence.** Identifiers named in a request body must resolve, each reporting its own code: `creator_id` yields `ERR_CREATOR_NOT_FOUND`, `assignment_id` yields `ERR_ASSIGNMENT_NOT_FOUND`, `issue_id` yields `ERR_ISSUE_NOT_FOUND`, `retailer_id` yields `ERR_RETAILER_NOT_FOUND`, `title_id` yields `ERR_TITLE_NOT_FOUND`, and a member of `variant_cover_ids` that does not exist, or that belongs to a different issue than the one being solicited, yields `ERR_VARIANT_COVER_NOT_FOUND`. This applies to assignment creation, production-stage booking, solicitation drafting, order drafting, revenue-event posting and statement creation.
6. **Resource ownership** for entity-backed identities, as specified in §2.1, otherwise `ERR_FORBIDDEN_RESOURCE` (403).
7. **Optimistic concurrency,** comparing `expected_title_version` against the title's `version` on assignment creation and `expected_issue_version` against the issue's `version` on print-run creation, otherwise `ERR_STALE_TITLE_VERSION` or `ERR_STALE_ISSUE_VERSION` (412).
8. **Transition legality.** The target resource is in a state from which the requested transition exists, including terminal-state lockdown and rejection of a repeated trigger, otherwise `ERR_INVALID_STATE` (409). Two cases are deliberately carved out of this generic check and deferred to step 9 so that they report a domain-specific code instead: cancelling an order that has already shipped, and reversing a statement that has already been paid.
9. **Trade-terms finality.** A `SHIPPED` order is never cancellable (`ERR_RETURNS_NOT_PERMITTED`) and a `PAID` statement is never reversible (`ERR_STATEMENT_ALREADY_PAID`), both 409.
10. **Cross-entity state gates** (all 409): the title must be `GREENLIT`, `IN_PRODUCTION` or `PUBLISHING` for assignment creation and for issue creation (`ERR_TITLE_NOT_GREENLIT`); the referenced assignment must be `ACCEPTED` or `ACTIVE` for stage start (`ERR_ASSIGNMENT_NOT_ACCEPTED`); the catalog must be `LOCKED` for solicitation acceptance (`ERR_CATALOG_NOT_LOCKED`); the issue must be `SOLICITED`, or `ON_SALE` in the reorder case, for order submission (`ERR_ISSUE_NOT_SOLICITED`); the retailer must be `ACTIVE` for order submission and for invoicing (`ERR_RETAILER_NOT_ACTIVE`); the issue's production dimension must be `CAMERA_READY` for print completion and for release (`ERR_NOT_CAMERA_READY`); and the issue's `printed_units` must be at least its `total_ordered_units` for shipping (`ERR_PRINT_NOT_COMPLETE`).
11. **Segregation of duties** on statement payment, `ERR_SEGREGATION_OF_DUTIES` (409).
12. **Non-returnable acknowledgement** on order submission and invoicing, `ERR_NON_RETURNABLE_ACK_REQUIRED` (409).
13. **Negotiation discipline** on reproposal, `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` (409).
14. **Solicitation submission window** on solicitation submission, `ERR_SOLICITATION_WINDOW_CLOSED` (409).
15. **Catalog deadline lapse** on catalog lock, `ERR_CATALOG_DEADLINE_NOT_PASSED` (409).
16. **Cut-off and on-sale timing** on final-order-cut-off lock, order adjustment and release: `ERR_FOC_NOT_REACHED`, `ERR_FOC_ALREADY_PASSED` and `ERR_ON_SALE_DATE_NOT_REACHED` (409).
17. **Digital embargo** on release-window creation, `ERR_DIGITAL_EMBARGO_VIOLATION` (422).
18. **Collected-edition blackout** on release-window creation, `ERR_CANNIBALIZATION_WINDOW_CONFLICT` (409).
19. **Creator booking overlap** on assignment creation, `ERR_CREATOR_DOUBLE_BOOKED` (409).
20. **On-sale cadence buffer** on issue creation, `ERR_ON_SALE_CADENCE_CONFLICT` (409).
21. **Reprint blackout** on print-run creation, `ERR_COLLECTED_EDITION_CONFLICT` (409).
22. **Uniqueness** (409): `issue_number` per title (`ERR_DUPLICATE_ISSUE_NUMBER`) on issue creation; variant-cover `code` per issue (`ERR_DUPLICATE_VARIANT_CODE`) on cover creation; at most one solicitation per catalog-and-issue pair among rows that are `DRAFT`, `SUBMITTED` or `ACCEPTED` (`ERR_DUPLICATE_SOLICITATION`) on solicitation drafting; at most one statement per title, creator, `period` and `basis` among rows that are `DRAFT`, `ISSUED` or `PAID` (`ERR_DUPLICATE_STATEMENT_PERIOD`) on statement creation; and `ERR_INVALID_REQUEST` for a duplicate `solicitation_month` on catalog creation, a duplicate `account_no` on retailer creation, and a duplicate title `name` on title creation.
23. **Catalog capacity** on solicitation acceptance, `ERR_CATALOG_SLOTS_EXHAUSTED` (409).
24. **Craft and scope coherence** (all 422): the assignment's `craft` must be a member of the creator's `crafts` (`ERR_CRAFT_NOT_SUPPORTED`); a stage's `craft` must equal the referenced assignment's `craft` (`ERR_CRAFT_MISMATCH`); the referenced assignment's title must be the issue's title (`ERR_TITLE_SCOPE_MISMATCH`); a `RATIO_INCENTIVE` cover must supply an `incentive_ratio` of 10, 25, 50 or 100 and every other cover kind must omit it (`ERR_VARIANT_RATIO_INVALID`); and a positive `exclusive_variant_qty` requires the issue to carry a `RETAILER_EXCLUSIVE` cover (`ERR_VARIANT_NOT_AVAILABLE`). These apply to assignment creation, production-stage booking, variant-cover creation, and order drafting and adjustment.
25. **Required related rows** (all 409): at least one `SUBMITTED` order at cut-off lock and a non-empty locked order book for an order-driven printing (`ERR_NO_QUALIFYING_ORDERS`); at least one `ACCEPTED` solicitation at catalog publication (`ERR_NO_ACCEPTED_SOLICITATIONS`); a `STANDARD` cover on the issue before its solicitation may be submitted (`ERR_STANDARD_COVER_REQUIRED`); a production stage for every required craft on the issue before a print run may be created for it and again before that run may be completed (`ERR_REQUIRED_CRAFT_STAGES_MISSING`); and an `ACCEPTED`, `ACTIVE` or `COMPLETED` assignment for the statement's creator on the statement's title (`ERR_NO_ASSIGNMENT_FOR_CREATOR`).
26. **Royalty pool budget** on assignment acceptance, `ERR_ROYALTY_SHARE_POOL_EXCEEDED` (422).
27. **Credit control** on order submission and invoicing, `ERR_CREDIT_LIMIT_EXCEEDED` (402).
28. **Zero-payable guard** on statement payment, `ERR_ZERO_PAYABLE_STATEMENT` (422).

### 2.11. Segregation of Duties and Non-Returnable Trade Terms

Two policies cut across the whole system and are worth stating once, centrally, before the workflows that enforce them.

The first is segregation of duties in money-out. A royalty statement records the operator identifier that issued it in `issued_by_user_id`; when a statement is paid, the acting `X-User-ID` must differ from that recorded value, and an attempt by the same operator to pay a statement they themselves issued is rejected with `ERR_SEGREGATION_OF_DUTIES`. Payment therefore requires either a second `RoyaltyAccountant` user or the `EditorInChief`, and the paying operator's identifier is recorded in `paid_by_user_id`.

The second is the non-returnable nature of direct-market trade. A retailer account carries a `non_returnable_ack` flag, and until that flag is true the account may neither submit an order nor be invoiced; either attempt is rejected with `ERR_NON_RETURNABLE_ACK_REQUIRED`. Once an order has shipped it is final: no cancellation, credit or return is possible, and an attempt is rejected with `ERR_RETURNS_NOT_PERMITTED`. This is also why a title cancellation, which unwinds nearly everything in its path, deliberately leaves already-shipped orders untouched.

## 3. Business Logic & Workflows

### 3.1. Greenlighting a Title and Committing Its Royalty Pool

Everything in the system hangs from a **Title**. An `EditorInChief` pitches one by supplying its `name` (1 to 160 characters, and unique across all titles), the `planned_issue_count` of the greenlit run (at least 1 and at most 24), the `royalty_pool_bps` share of channel net receipts that will form the creator royalty pool (from 1 to 3000 basis points), and the `cover_participation_bps` share of each channel pool that cover artists take before the pro-rata split (from 0 to 3000 basis points). A newly pitched title arrives in status `PITCHED` with `committed_share_bps`, `production_cost_cents` and `royalty_accrued_cents` all at 0, and with `greenlit_at` and `cancel_reason` both null.

A pitch is not staffable. Greenlighting the title — available only from `PITCHED`, and reported as `ERR_INVALID_STATE` from anywhere else — advances it to `GREENLIT`, stamps `greenlit_at` with the logical clock and bumps the title's `version`. Only from that point may creative assignments and issues be created; either attempt against a `PITCHED`, `COMPLETED` or `CANCELLED` title is refused with `ERR_TITLE_NOT_GREENLIT`, while a title that has moved on to `IN_PRODUCTION` or `PUBLISHING` remains staffable.

Creators are registered independently of any title. A `Creator` record carries a `full_name` of 1 to 120 characters as it will appear on the credits page, a non-empty `crafts` array of distinct values drawn from `SCRIPT`, `PENCILS`, `INKS`, `COLORS`, `LETTERS` and `COVER`, and a `default_page_rate_cents` of at least 0 that serves as the fallback rate quoted when a title does not override it. The creator's `active_assignment_count`, which starts at 0, is a derived count of that creator's assignments whose status is `PROPOSED`, `COUNTERED`, `ACCEPTED` or `ACTIVE`.

Staffing a title is the `EditorInChief`'s exclusive act. The offer names the `creator_id` of the person being hired, the `craft` slot being filled (one of the same six craft values), the `page_rate_cents` offered per delivered page (at least 0), the `royalty_share_bps` offered out of the post-cover remainder (from 0 to 10000 basis points), the half-open studio booking window `booking_start_date` (inclusive) and `booking_end_date` (exclusive, and strictly later than the start), an optional recoupable `advance_cents` that defaults to 0, and the `expected_title_version` demanded by §2.9. The offered craft must be one of the crafts the creator declared, or the offer is refused with `ERR_CRAFT_NOT_SUPPORTED`. A creator's studio time may not be double-sold: the new half-open interval must not intersect any existing booking interval of the same creator on an assignment whose status is `PROPOSED`, `COUNTERED`, `ACCEPTED` or `ACTIVE`, and an intersection is refused with `ERR_CREATOR_DOUBLE_BOOKED`. Because the intervals are half-open, two bookings that merely touch — the earlier one's `booking_end_date` equal to the new one's `booking_start_date` — are permitted. A successful offer creates the assignment in status `PROPOSED` with `negotiation_round` at 1, `unrecouped_advance_cents` initialised to the same value as `advance_cents`, `counter_page_rate_cents`, `counter_royalty_share_bps` and `terminated_reason` all null, and it refreshes the creator's `active_assignment_count` as well as the title's `version`.

Negotiation is a bounded cycle. The named creator, and only that creator, may counter the offer, which moves the assignment `PROPOSED → COUNTERED` and stores the asked-for `counter_page_rate_cents` and `counter_royalty_share_bps` on the row. The `EditorInChief` may then repropose, which moves it `COUNTERED → PROPOSED`, overwrites `page_rate_cents` and `royalty_share_bps` with the reproposed terms, clears both counter fields back to null, and increments `negotiation_round` by one. At most three rounds are permitted: a reproposal is refused with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` once `negotiation_round` has already reached 3, so the third counter is the creator's last word.

Acceptance is the creator's act and is the moment the title's royalty pool is committed. It is legal only from `PROPOSED`, only by the creator named on the assignment, and only while the title is `GREENLIT`, `IN_PRODUCTION` or `PUBLISHING`. For any craft other than `COVER`, the pool budget must hold: the title's current `committed_share_bps` plus the assignment's `royalty_share_bps` must be no greater than 10000 basis points less the title's `cover_participation_bps`. An acceptance that would push the roster past that ceiling is refused with `ERR_ROYALTY_SHARE_POOL_EXCEEDED`. On success the assignment becomes `ACCEPTED` and the title's `committed_share_bps` — the sum of `royalty_share_bps` over its non-`COVER` assignments whose status is `ACCEPTED`, `ACTIVE` or `COMPLETED` — is recomputed. `COVER`-craft assignments are deliberately outside this budget, because cover artists are paid from the separately reserved cover participation rather than from the pro-rata remainder.

An offer that will not be agreed can be terminated by the `EditorInChief` from `PROPOSED`, `COUNTERED`, `ACCEPTED` or `ACTIVE`, provided no production stage of that assignment is currently `IN_PROGRESS` or `DELIVERED` — work in flight must be resolved first. Termination captures the supplied `reason` into `terminated_reason`, moves the assignment to `TERMINATED`, and refreshes both the title's `committed_share_bps` and the creator's `active_assignment_count`. `COMPLETED` and `TERMINATED` are terminal states for an assignment.

### 3.2. Building the Issue Slate and Its Production Board

A `ManagingEditor` schedules the individual **Issues** of a greenlit title. Each issue declares its `issue_number` within the title (at least 1, and unique among that title's issues, with a repeat refused as `ERR_DUPLICATE_ISSUE_NUMBER`), its interior `page_count` (from 1 to 64), its standard `cover_price_cents` (at least 1), and its planned direct-market `target_on_sale_date`. The service derives the issue's Final Order Cut-off, `foc_date`, as the `target_on_sale_date` less three calendar weeks — twenty-one calendar days earlier. A publisher cannot flood a single shipping week, so the slate must keep its cadence: the absolute difference in calendar days between a new issue's `target_on_sale_date` and that of any sibling issue of the same title whose commercial dimension is not `CANCELLED` must be at least twenty-one days, and a closer date is refused with `ERR_ON_SALE_CADENCE_CONFLICT`. A new issue starts with `production_status` `PLANNED`, `commercial_status` `UNSOLICITED`, `schedule_health` `ON_TRACK`, `total_slip_days`, `total_ordered_units`, `printed_units` and `shipped_units` all 0, and `on_sale_date` null. Creating the very first issue of a title also moves that title from `GREENLIT` to `IN_PRODUCTION` and bumps its `version`.

An issue carries **two independent status dimensions**. The `production_status` dimension takes the values `PLANNED`, `SCRIPTING`, `ART`, `PREPRESS`, `CAMERA_READY` and `CANCELLED` and is never written directly by a client — it is re-derived from the issue's stage rows. The `commercial_status` dimension takes the values `UNSOLICITED`, `SOLICITED`, `FOC_LOCKED`, `PRINTED`, `ON_SALE` and `CANCELLED` and is advanced by solicitation, cut-off, printing and release actions. The two run independently, and exactly one operation in the entire system reads both dimensions of the same row: putting the issue on sale. Alongside them sits a third, derived posture, `schedule_health`, taking `ON_TRACK`, `AT_RISK` or `SLIPPED`.

The production board is built by booking **Production Stages** against accepted creative work. A `ManagingEditor` books a stage on an issue by naming the `assignment_id` that will perform it, the `craft` it covers, and its `planned_start_date` and `planned_due_date` (the due date on or after the start date). Two coherence rules bind the booking: the stage's `craft` must equal the craft on the referenced assignment, or the booking is refused with `ERR_CRAFT_MISMATCH`; and the referenced assignment must belong to the same title as the issue, or it is refused with `ERR_TITLE_SCOPE_MISMATCH`. A booked stage arrives in status `NOT_STARTED` with `slip_days` 0, `kickback_count` 0, `page_fee_cents` 0, and `actual_delivered_at` and `delivered_pages` both null.

The five **required crafts** for a printable comic are `SCRIPT`, `PENCILS`, `INKS`, `COLORS` and `LETTERS`; `COVER` work is booked and paid the same way but is not part of that required set. After any change whatsoever to an issue's stage set — a booking, a start, a delivery, a kick-back, an approval or a cancellation — the issue's `production_status` is re-derived from the statuses of its stage rows by exactly these rules:

- An issue with no stage rows at all is `PLANNED`.
- The issue advances `PLANNED → SCRIPTING` once it has at least one stage row and none of its `SCRIPT` stages has reached `APPROVED`.
- It advances `SCRIPTING → ART` once every `SCRIPT` stage of the issue is `APPROVED` while at least one stage whose craft is `PENCILS`, `INKS` or `COLORS` is not yet `APPROVED`.
- It advances `ART → PREPRESS` once every stage whose craft is `SCRIPT`, `PENCILS`, `INKS` or `COLORS` is `APPROVED` while at least one `LETTERS` stage is not yet `APPROVED`.
- It advances `PREPRESS → CAMERA_READY` once the issue carries at least one stage for each of the five required crafts **and** every one of its stages is `APPROVED`.
- It regresses `ART → SCRIPTING` when a further `SCRIPT` stage is booked onto an issue already in `ART`: the new stage arrives `NOT_STARTED`, so "every `SCRIPT` stage is approved" stops holding while at least one `PENCILS`, `INKS` or `COLORS` stage is still unapproved. Because an `APPROVED` stage is terminal and can never be kicked back, booking a late co-writer or rewrite stage is the only way the production dimension crosses a craft boundary backwards.
- In every other case the derived value stays where it was. Two consequences follow and are intended: a kick-back holds the issue inside its current phase rather than pushing it back a phase, and an issue whose stages are all approved but whose required-craft set is incomplete never reaches `CAMERA_READY` — it sits in whatever phase it had reached, which is precisely the condition that later surfaces as `ERR_REQUIRED_CRAFT_STAGES_MISSING` at printing time.

Whenever the re-derived value differs from the stored one, the issue row is mutated and its `version` increments. A stage may not be booked onto an issue whose production dimension is already `CANCELLED`.

### 3.3. Delivery, Lateness and the Schedule-Slip Cascade

Work begins when the assigned creator, and nobody else, starts a stage. Starting is legal from `NOT_STARTED` and from `KICKED_BACK`; from `NOT_STARTED` the referenced assignment must be `ACCEPTED` or `ACTIVE`, and from `KICKED_BACK` it must be `ACTIVE`, with any other assignment status refused as `ERR_ASSIGNMENT_NOT_ACCEPTED`. The issue's production dimension must not be `CANCELLED`. A start moves the stage to `IN_PROGRESS`, promotes the assignment `ACCEPTED → ACTIVE` where applicable, and re-derives the issue's production dimension.

Delivery is where the editorial calendar meets the commercial one. The assigned creator delivers from `IN_PROGRESS`, reporting `delivered_pages`, which must be at least 1 and no greater than the issue's `page_count`; anything outside that range is `ERR_INVALID_REQUEST`. The delivery stamps `actual_delivered_at` with the logical clock, stores `delivered_pages`, and moves the stage `IN_PROGRESS → DELIVERED`.

Lateness is then measured, and it is **recomputed rather than accumulated**. The stage's `slip_days` becomes the number of whole calendar days by which the delivery instant's UTC date falls after the `planned_due_date`'s UTC date, floored at 0 so an early or on-time delivery scores no slip at all. Each redelivery after a kick-back overwrites the previous value outright; the earlier round's lateness is discarded, which means an issue's total slip can genuinely **decrease** when a second delivery lands closer to the planned due date than the first did. The issue's `total_slip_days` is then re-summed from scratch as the sum of `slip_days` over that issue's stages whose status is `DELIVERED`, `KICKED_BACK` or `APPROVED`; stages that are `NOT_STARTED`, `IN_PROGRESS` or `CANCELLED` contribute nothing, and a `KICKED_BACK` stage keeps the slip of the rejected delivery until its next delivery overwrites it.

From that single number the issue's `schedule_health` posture is derived, with both thresholds inclusive upper bounds: a total of no more than one week of slip — seven days or fewer — is `ON_TRACK`; more than seven days but no more than three weeks, twenty-one days, is `AT_RISK`; and anything beyond twenty-one days is `SLIPPED`. So twenty-one days of accumulated slip is still `AT_RISK`, and twenty-two days is the first value that is `SLIPPED`.

When and only when that derivation turns the posture into `SLIPPED`, a four-hop cascade unwinds the book's commercial commitments inside the same request. Hop one is the slip measurement itself: the stage's `slip_days`, then the issue's `total_slip_days`, then the issue's `schedule_health`. Hop two, caused by the posture becoming `SLIPPED`, withdraws the book from the catalog: every solicitation of that issue whose status is `SUBMITTED` or `ACCEPTED` moves to `WITHDRAWN` with `withdrawn_reason` set to the literal string `AUTO_SLIP`, and the issue's commercial dimension returns to `UNSOLICITED` if it was `SOLICITED` or `FOC_LOCKED`. The backwards edge out of `FOC_LOCKED` is taken only while no print run of the issue has reached `PRINTED` — once presses have run, the lock stands. Because the cascade acts as the system rather than as an operator, it withdraws solicitations regardless of whether their catalog has already been published, which the operator-driven withdrawal does not permit. Hop three, caused by those withdrawals, refreshes `accepted_slot_count` on every affected catalog and cancels the issue's order book: every retailer order of that issue whose status is `SUBMITTED` or `FOC_LOCKED` moves to `CANCELLED` with `cancel_reason` set to the literal string `AUTO_SLIP`. Hop four, caused by those cancellations, refreshes each affected retailer's `cumulative_units_ytd`, re-derives that retailer's `discount_tier` from the refreshed figure — a demotion is entirely possible here — refreshes each affected retailer's `open_balance_cents`, and refreshes the issue's `total_ordered_units`. Finally the issue's production dimension is re-derived, and every row touched along the way has its `version` incremented.

Editorial review of a delivery has two outcomes, both reserved to a `ManagingEditor` and both legal only from `DELIVERED`. A kick-back moves the stage `DELIVERED → KICKED_BACK`, records the reviewer's `note`, increments `kickback_count` by one, and re-derives the issue's production dimension — which, per §3.2, holds the issue inside its current phase. An approval moves the stage `DELIVERED → APPROVED` and freezes its page fee: `page_fee_cents` becomes the referenced assignment's `page_rate_cents` at the moment of approval multiplied by the stage's `delivered_pages`, an exact integer product in cents. Because the fee is frozen, a later reproposal of that assignment's page rate can never move an already-approved fee. The title's `production_cost_cents` is then refreshed as the sum of `page_fee_cents` over the approved stages of all that title's issues. Approval also completes engagements: when every stage booked against the referenced assignment has reached `APPROVED`, that assignment moves `ACTIVE → COMPLETED` and the creator's `active_assignment_count` is recomputed. `APPROVED` and `CANCELLED` are terminal states for a stage.

### 3.4. Solicitation Catalogs and the Direct Market Announcement

Months before a book ships, its cover and copy must appear in a distributor catalog. A `SalesDirector` opens a **Catalog** for a `solicitation_month` — a `YYYY-MM` string, unique across catalogs — with a `submission_deadline` giving the last logical-clock instant at which a listing may be submitted into it (the deadline instant itself still counts as inside the window), an `on_sale_month` in the same `YYYY-MM` form naming the month whose issues this catalog solicits and which must fall strictly after the `solicitation_month`, and a `max_slots` cap of at least 1 on how many listings it can accept. A new catalog is `OPEN` with `accepted_slot_count` 0 and `published_at` null.

A **Solicitation** is drafted into a catalog by a `ManagingEditor`. The listing records the `catalog_id` of the catalog it was drafted into, taken from the path rather than the body, and names the `issue_id` being listed, a `cover_image_url` that must begin with `https://`, the `copy_text` that will be printed (from 40 to 1200 characters), and optionally the `variant_cover_ids` array of covers to advertise in that copy — a plain array of identifiers, each of which must belong to the issue being solicited, with any stray or foreign member refused as `ERR_VARIANT_COVER_NOT_FOUND`, and which defaults to the empty array. The same issue may not be listed twice in the same catalog: if that catalog already holds a listing for that issue in `DRAFT`, `SUBMITTED` or `ACCEPTED` status, the draft is refused with `ERR_DUPLICATE_SOLICITATION`. A drafted listing is `DRAFT` with `submitted_at` and `withdrawn_reason` null.

Submitting a listing, also a `ManagingEditor` act, moves it `DRAFT → SUBMITTED` and stamps `submitted_at` from the logical clock. Four conditions gate it. The catalog must still be `OPEN` and the issue's production dimension must be one of `SCRIPTING`, `ART`, `PREPRESS` or `CAMERA_READY` — a `PLANNED` or `CANCELLED` issue has nothing to solicit — with either failure reported as `ERR_INVALID_STATE`. The logical clock must be at or before the catalog's `submission_deadline`, or the attempt is refused with `ERR_SOLICITATION_WINDOW_CLOSED`. And the issue must already carry at least one `STANDARD` variant cover, since that is the cover the catalog prints and the one retailers order against; without it the attempt is refused with `ERR_STANDARD_COVER_REQUIRED`.

Locking the catalog is a manual `SalesDirector` act, which means a deadline can lapse while the catalog is still `OPEN` and accepting nothing. The lock moves the catalog `OPEN → LOCKED` and requires the logical clock to be strictly after the `submission_deadline`; an early attempt is refused with `ERR_CATALOG_DEADLINE_NOT_PASSED`.

Only a locked catalog can have its slate chosen. Accepting a listing, a `SalesDirector` act, moves it `SUBMITTED → ACCEPTED` and refreshes the catalog's `accepted_slot_count`. The catalog must be `LOCKED`, or the attempt is refused with `ERR_CATALOG_NOT_LOCKED`; and its `accepted_slot_count` must still be strictly below `max_slots`, with a full catalog refusing further acceptances via `ERR_CATALOG_SLOTS_EXHAUSTED`. A `SalesDirector` may withdraw a listing that is `SUBMITTED` or `ACCEPTED`, capturing the supplied `reason` into `withdrawn_reason` and refreshing `accepted_slot_count`, provided the catalog has not yet been published; a withdrawal attempt against a published catalog is refused as `ERR_INVALID_STATE`. `WITHDRAWN` is terminal for a listing.

Publication is the announcement to the direct market. A `SalesDirector` moves the catalog `LOCKED → PUBLISHED`, which stamps `published_at` from the logical clock and requires at least one accepted listing — a catalog whose `accepted_slot_count` is 0 is refused with `ERR_NO_ACCEPTED_SOLICITATIONS`. Publication then fans out across that catalog's accepted listings: every issue they reference moves its commercial dimension `UNSOLICITED → SOLICITED`, and each such issue's `version` increments. `PUBLISHED` is terminal for a catalog.

### 3.5. Variant Covers, the Retailer Order Book and the Final Order Cut-Off

Incentive covers are the direct market's demand lever, and they are created by a `SalesDirector` on the issue as immutable **Variant Cover** rows. Each carries a `code` of 1 to 8 characters as printed in the catalog, unique among that issue's covers (a repeat is `ERR_DUPLICATE_VARIANT_CODE`), a `kind` of `STANDARD`, `RATIO_INCENTIVE` or `RETAILER_EXCLUSIVE`, its own billed `cover_price_cents` of at least 1, and an optional `allocation_cap` of at least 1 capping how many copies of that cover any single order may earn — a null cap means uncapped. A `RATIO_INCENTIVE` cover must declare an `incentive_ratio` of exactly 10, 25, 50 or 100, naming how many standard copies a retailer must order to earn one of it; every other kind must omit the field entirely, and either mistake is refused with `ERR_VARIANT_RATIO_INVALID`. Covers cannot be added to an issue whose commercial dimension is `CANCELLED`.

Retailer accounts are opened by a `SalesDirector` with a unique `account_no`, a store `name`, a `credit_limit_cents` of at least 0 bounding the open balance the account may carry, the `non_returnable_ack` acknowledgement flag of §2.11, and an optional `opening_units_ytd` of at least 0 recording units already billed this year before this system took over the account (defaulting to 0). A new account is `ACTIVE` with `suspension_reason` null, its `cumulative_units_ytd` equal to its `opening_units_ytd`, its `open_balance_cents` 0, and its `discount_tier` derived immediately from those opening units. A `SalesDirector` may suspend an `ACTIVE` account, capturing the supplied `reason` into `suspension_reason`, and may reinstate a `SUSPENDED` one, which clears `suspension_reason` back to null. A suspended account keeps every ledger figure it had and keeps any orders already locked at cut-off, but it may neither submit new orders nor be invoiced, both refused with `ERR_RETAILER_NOT_ACTIVE`.

Volume earns discount, and the tier is a pure function of `cumulative_units_ytd` with inclusive thresholds: from 25,000 cumulative units upwards the account is `PREMIER`; from 10,000 up to but not reaching 25,000 it is `CORE`; from 2,500 up to but not reaching 10,000 it is `BASIC`; and below 2,500 it is `ENTRY`. So 2,500 cumulative units is already `BASIC` while 2,499 is still `ENTRY`. The tier is re-derived every time `cumulative_units_ytd` changes — at the cut-off lock, on order cancellation, and in the title-cancellation cascade — and because that figure is a recompute, the tier can demote as well as promote.

A `Retailer` drafts an order for itself, naming the `retailer_id` (which must equal `X-User-ID`), the `issue_id` ordered, the `standard_qty` of standard-cover copies wanted (at least 1 — this is the only quantity that earns incentive covers), and optionally an `exclusive_variant_qty` of retailer-exclusive copies requested, defaulting to 0. A positive exclusive request requires the issue to actually carry a `RETAILER_EXCLUSIVE` cover, or the draft is refused with `ERR_VARIANT_NOT_AVAILABLE`. The draft arrives `DRAFT` with `total_units` 0, `earned_variant_allocations` empty, `discount_tier_applied` null, `merchandise_net_cents`, `handling_fee_cents` and `invoice_total_cents` all 0, and `cancel_reason` null. At creation time the service also freezes `is_reorder`: it is true when the ordered issue's commercial dimension is already `ON_SALE`, and false otherwise. Reorders exist to restock a book that is already shipping, and they never earn incentive covers.

Submission moves the order `DRAFT → SUBMITTED` and is the retailer's own act on its own order. The retailer must be `ACTIVE` and must have acknowledged non-returnable terms. The issue must be `SOLICITED` for an initial order, or `ON_SALE` for a reorder, with any other commercial status refused as `ERR_ISSUE_NOT_SOLICITED`. And the account must still have credit headroom: at submission the comparison is **strict**, so the retailer's `open_balance_cents` must be strictly less than its `credit_limit_cents`, and an account sitting exactly on its limit may not open new business — that refusal is `ERR_CREDIT_LIMIT_EXCEEDED` with HTTP 402.

Until the cut-off, quantities remain fluid. A retailer may adjust its own `SUBMITTED` order repeatedly, replacing `standard_qty` with the newly requested quantity and, when supplied, replacing `exclusive_variant_qty` as well; the order stays `SUBMITTED` and only its `version` moves. Adjustment is a pre-cut-off privilege: the logical clock must be strictly before the issue's `foc_date`, and an attempt at or after that instant is refused with `ERR_FOC_ALREADY_PASSED`. As at draft time, a positive exclusive request still requires a `RETAILER_EXCLUSIVE` cover on the issue.

The **Final Order Cut-off lock** is the hinge of the whole commercial flow and belongs to the `SalesDirector`. It moves the issue `SOLICITED → FOC_LOCKED`, requires the logical clock to have reached the issue's `foc_date` (an earlier attempt is `ERR_FOC_NOT_REACHED`), and requires at least one `SUBMITTED` order for the issue (an empty book is `ERR_NO_QUALIFYING_ORDERS`). It then walks that issue's `SUBMITTED` orders in ascending `created_at` order and, for each one, computes and freezes the earned incentive allocations and the order's `total_units`, then moves the order `SUBMITTED → FOC_LOCKED`. Downstream in the same request, each affected retailer's `cumulative_units_ytd` is refreshed and its `discount_tier` re-derived, and the issue's `total_ordered_units` is refreshed. The issue's `version` and every locked order's `version` increment.

Allocation works as follows, for one order at a time. A reorder short-circuits: its `earned_variant_allocations` is the empty array and its `total_units` is simply its `standard_qty`. Otherwise the service walks **all** of the issue's variant covers — the covers are immutable, so there is no status filter — in one deterministic order: first grouped by kind in the fixed sequence `RATIO_INCENTIVE`, then `RETAILER_EXCLUSIVE`, then `STANDARD`; within a kind, by ascending `incentive_ratio` with covers having no ratio placed last; and within that, by ascending `code`. The covers' identifiers are never consulted for ordering. For each cover in that order:

- A `RATIO_INCENTIVE` cover earns the order's `standard_qty` divided by that cover's `incentive_ratio`, with the division floored to a whole copy, and the result then capped at the cover's `allocation_cap` when one is present. Because the division floors, a ratio only pays on exact multiples: 60 standard copies earn 6 copies of a 1-in-10 cover, while 9 standard copies earn none.
- A `RETAILER_EXCLUSIVE` cover earns nothing at all unless the ordering retailer is eligible, and eligibility means the retailer's `cumulative_units_ytd` — measured as it stands before this cut-off adds this order's own units — is at least 10,000 units. An eligible retailer earns the smaller of two figures: the `exclusive_variant_qty` it requested, and its `standard_qty` divided by 50 and floored to a whole copy. That result is then capped at the cover's `allocation_cap` when one is present.
- A `STANDARD` cover earns nothing: standard copies are billed straight from `standard_qty` and are never "earned".

Every cover that earns a positive quantity contributes one entry to `earned_variant_allocations`, in the walk order above, holding that cover's `variant_cover_id` and the earned `qty`. The order's `total_units` is then its `standard_qty` plus the sum of the `qty` values across those entries.

### 3.6. Invoicing, Shipping and Order Compensation

Invoicing a locked order is a `SalesDirector` act that moves it `FOC_LOCKED → INVOICED`. The retailer must be `ACTIVE` and must have acknowledged non-returnable terms. Credit control applies a second time here, and with a **different comparison** from the one at submission: the retailer's current `open_balance_cents` plus the invoice total that this operation computes must be no greater than its `credit_limit_cents`. That bound is inclusive — an invoice that lands exactly on the limit is accepted, and one cent more is refused with `ERR_CREDIT_LIMIT_EXCEEDED`.

The invoice is computed as follows. The tier is taken from the retailer's `discount_tier` as it stands at invoice time and frozen onto the order as `discount_tier_applied`; because the cut-off lock has already added this order's units to `cumulative_units_ytd`, the tier is inclusive of the very order being invoiced. The discount attached to each tier is 40 percent at `ENTRY`, 45 percent at `BASIC`, 50 percent at `CORE` and 55 percent at `PREMIER`, so the fraction actually billed is one minus that discount. The invoice is then built as lines: the first line is the standard line, whose quantity is the order's `standard_qty` and whose unit price is the `cover_price_cents` of the issue's `STANDARD` variant cover; each subsequent line comes from one entry of `earned_variant_allocations`, in the order stored there, with that entry's `qty` as the quantity and the `cover_price_cents` of the cover it names as the unit price.

The rounding order here is pinned and is part of the contract. For each line, the gross is the quantity multiplied by the unit price, and the line's net is that gross multiplied by the billed fraction and then rounded half up to a whole cent. `merchandise_net_cents` is the sum of those already-rounded line nets. Rounding each line first and summing afterwards is the required order; discounting the summed gross once and rounding at the end is a different figure and is wrong. `handling_fee_cents` is then a flat $9.95 — 995 cents — except that it is waived to 0 when `merchandise_net_cents` reaches $500.00, that is 50,000 cents, or more. `invoice_total_cents` is `merchandise_net_cents` plus `handling_fee_cents`. Once the invoice is written, the retailer's `open_balance_cents` is refreshed from its invoiced and shipped orders.

Shipping is the last commercial step and is the point at which print revenue is recognised. A `SalesDirector` moves an `INVOICED` order to `SHIPPED`, which is permitted only when the issue's `printed_units` is at least its `total_ordered_units` — an under-printed issue cannot ship, and the refusal is `ERR_PRINT_NOT_COMPLETE`. Shipment appends one immutable revenue event for that issue with `channel` `PRINT_DM`, `basis_status` `ACTUAL`, `source` `SHIPMENT`, `gross_receipts_cents` equal to the sum of the ordered lines' gross amounts (before any discount), `net_receipts_cents` equal to the order's `merchandise_net_cents`, `units` equal to the order's `total_units`, and `period` set to the `YYYY-MM` month of the logical clock. The issue's `shipped_units` is then refreshed. `SHIPPED` is terminal for an order, and no cancellation, credit or return can follow it.

Cancellation is the exact compensating action for everything the order book did, and who may perform it depends on how far the order has travelled. A retailer may cancel its own order while it is `DRAFT` or `SUBMITTED`; neither of those states has touched any ledger, so there is nothing to reverse and the cancellation simply captures the supplied `reason` into `cancel_reason`. From `FOC_LOCKED` or `INVOICED`, only a `SalesDirector` may cancel, because those states have already committed units and possibly money. Such a cancellation captures the `reason`, then refreshes the retailer's `cumulative_units_ytd` (the order's units leave the count), re-derives the retailer's `discount_tier` from that refreshed figure — which may demote the account — refreshes the retailer's `open_balance_cents` (the invoice, if there was one, leaves the balance), and refreshes the issue's `total_ordered_units`. The computed invoice figures stay on the cancelled row for the audit trail even though they no longer participate in any ledger. `CANCELLED` is terminal for an order.

### 3.7. Printings, Reprints, Release and Downstream Editions

Print quantities are decided by a `ManagingEditor`, who plans a **Print Run** on the issue by choosing a `basis` of either `ORDER_DRIVEN` or `DEMAND_FORECAST` and supplying the `expected_issue_version` demanded by §2.9. Before any run may be planned, the issue must carry a production stage for every one of the five required crafts; an issue that reached the cut-off carrying, say, only a script stage is refused with `ERR_REQUIRED_CRAFT_STAGES_MISSING`. The run's `printing_number` is assigned by the server: one greater than the highest `printing_number` among that issue's runs whose status is `PLANNED` or `PRINTED`, or 1 when the issue has no such run. A planned run is `PLANNED` with `printed_at` and `cancel_reason` null.

The two bases answer different questions and are deliberately both legal against the same database state, from which they produce different quantities. An `ORDER_DRIVEN` run may be planned while the issue's commercial dimension is `FOC_LOCKED`, `PRINTED` or `ON_SALE`. A `DEMAND_FORECAST` run — the second printing or reprint case — may be planned only while the issue is `PRINTED` or `ON_SALE` **and** the issue already has at least one run in `PRINTED` status. Choosing a basis outside its legal window is refused as `ERR_INVALID_STATE`. Reprints also respect the collected edition: planning a `DEMAND_FORECAST` run is refused with `ERR_COLLECTED_EDITION_CONFLICT` when the issue has a `COLLECTED` release window whose `release_date` falls within sixty calendar days after the logical clock.

Under the `ORDER_DRIVEN` basis, `order_base_units` is the sum of `total_units` over that issue's orders whose status is `FOC_LOCKED`, `INVOICED` or `SHIPPED`; `DRAFT`, `SUBMITTED` and `CANCELLED` orders are excluded, and a base of zero means there is nothing to print, refused with `ERR_NO_QUALIFYING_ORDERS`. `overprint_units` is eight percent of that base, rounded up to a whole copy. A raw figure is then formed as the base plus the overprint plus a fixed reserve of 150 copies, and the run's `quantity` is that raw figure rounded up to the next whole multiple of 250 copies — one carton — but never less than a 500-copy minimum first printing, whichever is larger.

Under the `DEMAND_FORECAST` basis, the calculation ignores the cut-off order book entirely and reads trailing velocity plus open restock demand instead. Prior print volume is the sum of `quantity` over that issue's runs whose status is `PRINTED`; reorder demand is the sum of `standard_qty` over that issue's orders that are still `SUBMITTED` and whose `is_reorder` is true. `order_base_units` is then thirty-five percent of the prior print volume, rounded half up to a whole copy, plus that reorder demand. `overprint_units` is 0 on this basis. The run's `quantity` is `order_base_units` rounded up to the next whole multiple of 250 copies, but never less than a 250-copy minimum reprint, whichever is larger.

Completing a run is a `ManagingEditor` act from `PLANNED`, and it requires the issue's production dimension to be `CAMERA_READY` — a book that is not camera-ready cannot go to press, refused with `ERR_NOT_CAMERA_READY` — as well as the full required-craft stage set. Completion stamps `printed_at` from the logical clock, moves the run `PLANNED → PRINTED`, and refreshes the issue's `printed_units`. When the completed run is the first printing, that is when its `printing_number` is 1, the issue's commercial dimension also moves `FOC_LOCKED → PRINTED`. A `PLANNED` run may instead be cancelled by a `ManagingEditor`, capturing the supplied `reason` into `cancel_reason` and refreshing the issue's `printed_units` — a recompute that cannot change the figure, since a run that never printed contributed nothing to it. `PRINTED` and `CANCELLED` are both terminal for a run.

Release is the one operation that reads both of an issue's status dimensions at once. A `SalesDirector` moves the issue `PRINTED → ON_SALE`, which requires the production dimension to be `CAMERA_READY` and requires the logical clock to have reached the issue's `target_on_sale_date`; an early release is refused with `ERR_ON_SALE_DATE_NOT_REACHED`. Release stamps `on_sale_date` from the logical clock and then bubbles up to the title: a title in `IN_PRODUCTION` moves to `PUBLISHING` on its first on-sale issue, and a title already `PUBLISHING` moves to `COMPLETED` at the moment the count of its issues with commercial dimension `ON_SALE` reaches its `planned_issue_count`. Only one of those two edges is taken per release: a release that moves the title from `IN_PRODUCTION` to `PUBLISHING` ends the bubble-up there and does not go on to test the `COMPLETED` condition inside the same request, so a title whose `planned_issue_count` is 1 is left in `PUBLISHING` when its only planned issue goes on sale. Both the issue's and the title's `version` increment.

Downstream editions are planned as immutable **Release Windows** on the issue by a `SalesDirector`, each naming a `channel` of `DIGITAL` or `COLLECTED`, a `release_date`, and an optional `expected_net_receipts_cents` planning figure of at least 0 that defaults to 0 and is never read by royalty accounting. The print window is the issue's own `on_sale_date` and is not stored as a release window. A window may be planned at any point in the issue's commercial life, including while it is still `UNSOLICITED`; the only state gate is that the issue must not be `CANCELLED`. Two cannibalization rules apply. A `DIGITAL` window must not land earlier than thirty calendar days after the issue's `target_on_sale_date`, that is, its `release_date` must be on or after that date plus thirty days, and an earlier date is refused with `ERR_DIGITAL_EMBARGO_VIOLATION` at HTTP 422. A `COLLECTED` window must fall strictly after ninety calendar days past the latest `target_on_sale_date` among that title's issues whose commercial dimension is not `CANCELLED`; the blackout end date itself is still inside the blackout, so only a date after it qualifies, and a violation is refused with `ERR_CANNIBALIZATION_WINDOW_CONFLICT`.

### 3.8. Revenue Events and Creator Royalty Accounting

Receipts reach the system as immutable **Revenue Events**, posted by a `RoyaltyAccountant` against an issue. Each names the `issue_id` that generated the money, the `channel` — `PRINT_DM`, `DIGITAL`, `COLLECTED` or `SUBSIDIARY` — a `basis_status` of `ESTIMATED` for provisional rows or `ACTUAL` for settled receipts, the `gross_receipts_cents` booked (at least 0), the `net_receipts_cents` after channel deductions (at least 0, and never more than the gross), an optional `units` count of at least 0 defaulting to 0, and the accounting `period` as a `YYYY-MM` string. Royalty pools are struck from `net_receipts_cents` and never from the gross. Accountant-posted rows carry `source` `MANUAL`; the rows the shipping step writes for itself carry `source` `SHIPMENT`, as described in §3.6.

A **Royalty Statement** is created by a `RoyaltyAccountant` for a `title_id`, a `creator_id`, a `period` in `YYYY-MM` form and a `basis` of either `ESTIMATED` or `SETTLED`. At most one statement may exist per title, creator, period and basis among rows that are `DRAFT`, `ISSUED` or `PAID`, with a repeat refused as `ERR_DUPLICATE_STATEMENT_PERIOD`. The statement is computed at creation and arrives in `DRAFT`.

Computation begins by finding the participant. The statement's assignment is the creative assignment for the same title and the same creator whose status is `ACCEPTED`, `ACTIVE` or `COMPLETED`, and where more than one qualifies, the one with the earliest `created_at` is taken; identifiers are never used as the tie-break. If no such assignment exists, statement creation is refused with `ERR_NO_ASSIGNMENT_FOR_CREATOR`. The contributing receipts are the revenue events belonging to any issue of that title whose `period` equals the statement's `period`, filtered by basis: an `ESTIMATED` statement includes both `ESTIMATED` and `ACTUAL` rows, while a `SETTLED` statement includes `ACTUAL` rows only.

The four channels are then walked in the fixed order `PRINT_DM`, `DIGITAL`, `COLLECTED`, `SUBSIDIARY`, and each contributes at most one entry to the statement's `lines`. For a channel, the raw net is the sum of `net_receipts_cents` over the contributing events of that channel; a channel whose raw net is zero emits no line at all. On an `ESTIMATED` statement, and only for the `PRINT_DM` channel, twenty percent of that raw net is held back as a returns reserve: the `included_net_cents` becomes eighty percent of the raw net, floored to a whole cent. In every other case — any channel on a `SETTLED` statement, and any channel other than `PRINT_DM` on an `ESTIMATED` one — `included_net_cents` is the raw net unchanged, with no holdback. The channel's `channel_pool_cents` is then the `included_net_cents` multiplied by the title's `royalty_pool_bps`, multiplied again by that channel's multiplier in basis points — 10000 for `PRINT_DM`, 20000 for `DIGITAL`, 12500 for `COLLECTED` and 40000 for `SUBSIDIARY` — divided by 100,000,000 and floored to a whole cent. That is a single floor over the whole expression, never two chained roundings.

Each channel pool is then split across the title's participants, and the split's evaluation order is pinned because the cover participation is keyed on the pool while the pro-rata remainder is keyed on what is left of it. The participants are that title's creative assignments whose status is `ACCEPTED`, `ACTIVE` or `COMPLETED`; assignments still `PROPOSED` or `COUNTERED`, and assignments that were `TERMINATED`, are excluded entirely and their basis points never enter any denominator. First, the cover portion is struck from the pool before any deduction: it is the pool multiplied by the title's `cover_participation_bps`, divided by 10000, and floored to a whole cent. That cover portion is then divided pro rata among the participants whose craft is `COVER`, each receiving the cover portion multiplied by their own `royalty_share_bps` and divided by the sum of `royalty_share_bps` across all `COVER` participants, floored to a whole cent, with any one-cent remainder handed out a cent at a time to those cover participants in ascending `created_at` order. If the title has no `COVER` participant at all, no cover share is paid and the struck cover portion is simply not distributed. Second, the remainder is the pool less that struck cover portion. Non-cover participants normalise over their **own** basis-point total rather than over 10000: each receives the remainder multiplied by their own `royalty_share_bps`, divided by the sum of `royalty_share_bps` across all non-`COVER` participants, floored to a whole cent. If that non-cover sum is zero, every non-cover share is zero. Finally the floored shares are topped up: the difference between the remainder and the sum of the floored shares is distributed one cent at a time to the non-cover participants in ascending `created_at` order until it is exhausted, so the distributed shares add up to the remainder exactly. Identifiers are never consulted for this ordering. Applying each participant's basis points directly to the whole pool instead of to the post-cover remainder would leave part of the pool undistributed and is not the specified behaviour.

Each emitted line therefore records its `channel`, its `included_net_cents`, its `channel_pool_cents`, and the `creator_share_cents` that the split awarded to this statement's own participant. The statement's `gross_royalty_cents` is the sum of `creator_share_cents` across its lines. Advances are recouped next: `recoupment_applied_cents` is the smaller of the assignment's `unrecouped_advance_cents` and the `gross_royalty_cents`, and `payable_cents` is the gross royalty less that recoupment. Because the two bases select different receipts and apply the returns reserve differently, the same database state legitimately yields two different statements for the same creator and period — an interim `ESTIMATED` figure and a final `SETTLED` one.

Issuing a statement is a `RoyaltyAccountant` act from `DRAFT`. It records the acting `X-User-ID` in `issued_by_user_id`, moves the statement `DRAFT → ISSUED`, and posts it to two ledgers: the title's `royalty_accrued_cents` grows by this statement's `payable_cents`, and the assignment's `unrecouped_advance_cents` falls by this statement's `recoupment_applied_cents`, both refreshed per the definitions in §2.7.

Paying an issued statement is open to a `RoyaltyAccountant` or the `EditorInChief`, and it moves the statement `ISSUED → PAID`, recording the acting `X-User-ID` in `paid_by_user_id` and the supplied `payment_reference` on the row. Two guards apply. The acting `X-User-ID` must differ from `issued_by_user_id`, per §2.11, or the attempt is refused with `ERR_SEGREGATION_OF_DUTIES`. And the statement's `payable_cents` must be strictly greater than 0: a statement whose entire accrual was absorbed by the advance may be issued for the record but never paid, and payment is refused with `ERR_ZERO_PAYABLE_STATEMENT` at HTTP 422.

Reversal is the exact compensating action for issuance. A `RoyaltyAccountant` moves an `ISSUED` statement to `REVERSED`, capturing the supplied `reason` into `reversal_reason`; the title's `royalty_accrued_cents` shrinks by this statement's `payable_cents` and the assignment's `unrecouped_advance_cents` is restored by this statement's `recoupment_applied_cents`, returning both figures to exactly their pre-issue values. A statement that has already been paid cannot be reversed and the attempt is refused with `ERR_STATEMENT_ALREADY_PAID`. `PAID` and `REVERSED` are both terminal for a statement.

### 3.9. Cancelling a Title and Unwinding Its Commitments

Cancellation is the `EditorInChief`'s largest single action, and it is available while the title is `PITCHED`, `GREENLIT`, `IN_PRODUCTION` or `PUBLISHING` — that is, from every non-terminal state, with an identical unwind body in each case. It captures the supplied `reason` into `cancel_reason`, moves the title to `CANCELLED`, and increments the title's `version`. `COMPLETED` and `CANCELLED` are terminal for a title, and a second cancellation is refused as `ERR_INVALID_STATE`.

The unwind runs as a chain of hops inside the same request. One branch releases the creative roster: every creative assignment of the title whose status is `PROPOSED`, `COUNTERED`, `ACCEPTED` or `ACTIVE` moves to `TERMINATED` with `terminated_reason` set to the literal string `AUTO_TITLE_CANCEL`, and then, caused by those terminations, each affected creator's `active_assignment_count` is recomputed. Note that the in-flight-work restriction that constrains an operator-driven termination does not hold the cascade back: the cascade cancels those very stages in the same request.

The other branch closes the slate. Every issue of the title whose commercial dimension is not already `CANCELLED` has both dimensions set to `CANCELLED`. Caused by that, for each issue just cancelled: its print runs in `PLANNED` status move to `CANCELLED` with `cancel_reason` set to the literal string `AUTO_TITLE_CANCEL`; its production stages in `NOT_STARTED`, `IN_PROGRESS`, `DELIVERED` or `KICKED_BACK` status move to `CANCELLED`, while `APPROVED` stages are deliberately left alone so that the title's `production_cost_cents` does not move; and its retailer orders in `DRAFT`, `SUBMITTED`, `FOC_LOCKED` or `INVOICED` status move to `CANCELLED` with `cancel_reason` set to `AUTO_TITLE_CANCEL`, while orders that have already shipped are left untouched under the non-returnable terms of §2.11. Caused in turn by those order cancellations, each affected retailer's `cumulative_units_ytd`, `discount_tier` and `open_balance_cents` are recomputed, and each affected issue's `total_ordered_units` is recomputed. Every row touched anywhere in this chain has its `updated_at` refreshed and its `version` incremented.

## 4. Endpoint Definitions

Operations that create a new resource — a creator, a title, a creative assignment, an issue, a production stage, a variant cover, a catalog, a solicitation, a retailer, an order, a print run, a release window, a revenue event or a royalty statement — return `201 Created`. Every other operation, including every state transition, every cancellation and the logical-clock capability, returns `200 OK`. Reads return `200 OK`. Failures return the status code listed against their error identifier in §5, and the request body of an action endpoint carries only the fields §3 attributes to it.

| Method | Path | Description | Authorized Role(s) |
| :--- | :--- | :--- | :--- |
| POST | `/_clock/set_current_utc` | Set the logical UTC clock that every temporal rule reads. | `EditorInChief`, `ManagingEditor`, `SalesDirector`, `RoyaltyAccountant`, `Creator`, `Retailer` |
| POST | `/comics/creators` | Register a creator with the crafts they can be assigned to. | `EditorInChief`, `ManagingEditor` |
| GET | `/comics/creators` | List creators. | `EditorInChief`, `ManagingEditor`, `RoyaltyAccountant` |
| GET | `/comics/creators/{id}` | Read one creator. | `EditorInChief`, `ManagingEditor`, `RoyaltyAccountant`, `Creator` |
| GET | `/comics/creators/{id}/creative-assignments` | List every assignment held by this creator. | `EditorInChief`, `ManagingEditor`, `RoyaltyAccountant`, `Creator` |
| POST | `/comics/titles` | Pitch a new title. | `EditorInChief` |
| GET | `/comics/titles` | List titles. | `EditorInChief`, `ManagingEditor`, `SalesDirector`, `RoyaltyAccountant` |
| GET | `/comics/titles/{id}` | Read one title including its derived ledgers. | `EditorInChief`, `ManagingEditor`, `SalesDirector`, `RoyaltyAccountant`, `Creator` |
| POST | `/comics/titles/{id}/greenlight` | Greenlight a pitched title so creative assignments and issues can be created. | `EditorInChief` |
| POST | `/comics/titles/{id}/cancel` | Cancel a title and unwind its creative, editorial and order commitments. | `EditorInChief` |
| POST | `/comics/titles/{id}/creative-assignments` | Assign a creator to a craft on this title with page rate, royalty share, advance and a studio booking window. | `EditorInChief` |
| GET | `/comics/titles/{id}/creative-assignments` | List the title's creative team. | `EditorInChief`, `ManagingEditor`, `RoyaltyAccountant` |
| POST | `/comics/titles/{id}/issues` | Schedule an issue of the title; the FOC date is derived from the on-sale date. | `ManagingEditor` |
| GET | `/comics/titles/{id}/issues` | List the title's issues. | `EditorInChief`, `ManagingEditor`, `SalesDirector` |
| GET | `/comics/creative-assignments/{id}` | Read one creative assignment including negotiation and advance state. | `EditorInChief`, `ManagingEditor`, `RoyaltyAccountant`, `Creator` |
| POST | `/comics/creative-assignments/{id}/counter` | Creator counters the offered page rate and royalty share. | `Creator` |
| POST | `/comics/creative-assignments/{id}/repropose` | Editor reproposes revised terms, closing one negotiation round. | `EditorInChief` |
| POST | `/comics/creative-assignments/{id}/accept` | Creator accepts the current terms, committing the title's royalty pool. | `Creator` |
| POST | `/comics/creative-assignments/{id}/terminate` | Terminate an assignment that will not be agreed. | `EditorInChief` |
| GET | `/comics/creative-assignments/{id}/production-stages` | List the stages booked against this assignment. | `EditorInChief`, `ManagingEditor`, `Creator` |
| GET | `/comics/issues/{id}` | Read one issue with both status dimensions and its derived counters. | `EditorInChief`, `ManagingEditor`, `SalesDirector`, `RoyaltyAccountant`, `Creator`, `Retailer` |
| POST | `/comics/issues/{id}/production-stages` | Book a production stage (script, pencils, inks, colors, letters) against an accepted assignment. | `ManagingEditor` |
| GET | `/comics/issues/{id}/production-stages` | List the issue's stages. | `EditorInChief`, `ManagingEditor`, `Creator` |
| POST | `/comics/issues/{id}/variant-covers` | Add a standard, ratio-incentive or retailer-exclusive cover to the issue. | `SalesDirector` |
| GET | `/comics/issues/{id}/variant-covers` | List the issue's covers. | `EditorInChief`, `SalesDirector`, `Retailer` |
| POST | `/comics/issues/{id}/foc-lock` | Lock the final order cut-off: freeze every submitted order's earned incentive covers and roll the retailer unit ledgers forward. | `SalesDirector` |
| POST | `/comics/issues/{id}/release` | Put a printed issue on sale. | `SalesDirector` |
| POST | `/comics/issues/{id}/print-runs` | Plan a printing for the issue; quantity is derived from the chosen basis. | `ManagingEditor` |
| GET | `/comics/issues/{id}/print-runs` | List the issue's printings. | `EditorInChief`, `ManagingEditor`, `SalesDirector` |
| POST | `/comics/issues/{id}/release-windows` | Schedule a digital or collected release window for the issue. | `SalesDirector` |
| GET | `/comics/issues/{id}/release-windows` | List the issue's release windows. | `EditorInChief`, `SalesDirector`, `RoyaltyAccountant` |
| GET | `/comics/issues/{id}/revenue-events` | List the issue's revenue events. | `SalesDirector`, `RoyaltyAccountant`, `EditorInChief` |
| GET | `/comics/issues/{id}/solicitations` | List the catalog solicitations that reference this issue. | `EditorInChief`, `ManagingEditor`, `SalesDirector` |
| GET | `/comics/production-stages/{id}` | Read one production stage including slip and page-fee state. | `EditorInChief`, `ManagingEditor`, `Creator` |
| POST | `/comics/production-stages/{id}/start` | Creator starts (or restarts after a kick-back) work on a stage. | `Creator` |
| POST | `/comics/production-stages/{id}/deliver` | Creator delivers pages; lateness is measured and a slip may unwind the issue's solicitation and order book. | `Creator` |
| POST | `/comics/production-stages/{id}/kick-back` | Editor rejects a delivery and sends the stage back for revision. | `ManagingEditor` |
| POST | `/comics/production-stages/{id}/approve` | Editor approves a delivery, freezing the page fee into the title's production cost ledger. | `ManagingEditor` |
| POST | `/comics/catalogs` | Open a monthly solicitation catalog with a submission deadline and a slot cap. | `SalesDirector` |
| GET | `/comics/catalogs` | List catalogs. | `EditorInChief`, `ManagingEditor`, `SalesDirector` |
| GET | `/comics/catalogs/{id}` | Read one catalog with its accepted slot count. | `EditorInChief`, `ManagingEditor`, `SalesDirector` |
| POST | `/comics/catalogs/{id}/lock` | Lock a catalog after its submission deadline so accepted slots can be chosen. | `SalesDirector` |
| POST | `/comics/catalogs/{id}/publish` | Publish the catalog to the direct market, opening retailer ordering for every accepted issue. | `SalesDirector` |
| POST | `/comics/catalogs/{id}/solicitations` | Draft a catalog solicitation for an issue with cover image, copy and the variant covers on offer. | `ManagingEditor` |
| GET | `/comics/catalogs/{id}/solicitations` | List the catalog's solicitations. | `EditorInChief`, `ManagingEditor`, `SalesDirector` |
| GET | `/comics/solicitations/{id}` | Read one solicitation. | `EditorInChief`, `ManagingEditor`, `SalesDirector` |
| POST | `/comics/solicitations/{id}/submit` | Submit the solicitation to the catalog before its deadline. | `ManagingEditor` |
| POST | `/comics/solicitations/{id}/accept` | Accept a submitted solicitation into a catalog slot. | `SalesDirector` |
| POST | `/comics/solicitations/{id}/withdraw` | Withdraw a submitted or accepted solicitation, releasing its catalog slot. | `SalesDirector` |
| POST | `/comics/retailers` | Open a direct-market retailer account with a credit limit and non-returnable terms acknowledgement. | `SalesDirector` |
| GET | `/comics/retailers` | List retailer accounts with their current discount tiers. | `EditorInChief`, `SalesDirector`, `RoyaltyAccountant` |
| GET | `/comics/retailers/{id}` | Read one retailer account including its unit and balance ledgers. | `EditorInChief`, `SalesDirector`, `RoyaltyAccountant`, `Retailer` |
| POST | `/comics/retailers/{id}/suspend` | Suspend a retailer account for credit or terms reasons. | `SalesDirector` |
| POST | `/comics/retailers/{id}/reinstate` | Reinstate a suspended retailer account. | `SalesDirector` |
| POST | `/comics/retailer-orders` | Retailer drafts an order for an issue with standard copies and an optional exclusive-cover request. | `Retailer` |
| GET | `/comics/retailer-orders` | List orders, filterable by retailer and issue. | `EditorInChief`, `SalesDirector`, `RoyaltyAccountant`, `Retailer` |
| GET | `/comics/retailer-orders/{id}` | Read one order including its frozen incentive allocations and invoice figures. | `EditorInChief`, `SalesDirector`, `RoyaltyAccountant`, `Retailer` |
| POST | `/comics/retailer-orders/{id}/submit` | Retailer submits the order against the solicited issue. | `Retailer` |
| POST | `/comics/retailer-orders/{id}/adjust` | Retailer adjusts quantities on a submitted order before the final order cut-off. | `Retailer` |
| POST | `/comics/retailer-orders/{id}/invoice` | Invoice a locked order at the retailer's discount tier with per-line rounding and a handling fee. | `SalesDirector` |
| POST | `/comics/retailer-orders/{id}/ship` | Ship an invoiced order once the issue has been printed in sufficient quantity. | `SalesDirector` |
| POST | `/comics/retailer-orders/{id}/cancel` | Cancel an order, exactly reversing its contribution to the retailer and issue ledgers. | `SalesDirector`, `Retailer` |
| GET | `/comics/print-runs/{id}` | Read one printing. | `EditorInChief`, `ManagingEditor`, `SalesDirector` |
| POST | `/comics/print-runs/{id}/complete` | Record a printing as printed, moving a first printing's issue to PRINTED. | `ManagingEditor` |
| POST | `/comics/print-runs/{id}/cancel` | Cancel a planned printing. | `ManagingEditor` |
| POST | `/comics/revenue-events` | Post a print, digital, collected or subsidiary revenue event for an issue in a royalty period. | `RoyaltyAccountant` |
| POST | `/comics/royalty-statements` | Compute a creator's royalty statement for a period on an estimated or settled basis. | `RoyaltyAccountant` |
| GET | `/comics/royalty-statements` | List statements, filterable by title and creator. | `EditorInChief`, `RoyaltyAccountant`, `Creator` |
| GET | `/comics/royalty-statements/{id}` | Read one statement with its per-channel lines. | `EditorInChief`, `RoyaltyAccountant`, `Creator` |
| POST | `/comics/royalty-statements/{id}/issue` | Issue the statement to the creator, posting it to the title and advance ledgers. | `RoyaltyAccountant` |
| POST | `/comics/royalty-statements/{id}/pay` | Pay an issued statement; the payer must not be the accountant who issued it. | `EditorInChief`, `RoyaltyAccountant` |
| POST | `/comics/royalty-statements/{id}/reverse` | Reverse an issued statement, exactly unwinding its ledger and advance-recoupment effects. | `RoyaltyAccountant` |

Beyond `limit` and `offset`, the list endpoints accept the following filters, each matching the field of the same name on the listed resource: `status` on creators' assignments, title assignments, issues' stages, an assignment's stages, print runs, solicitations, catalogs, retailers, orders, titles and statements; `craft` on creators, title assignments and an issue's stages; `commercial_status` and `production_status` on a title's issues; `kind` on an issue's covers; `basis` on print runs and statements; `channel` on release windows and revenue events; `basis_status` and `period` on revenue events; `period` on statements; `solicitation_month` on catalogs; `discount_tier` on retailers; and `retailer_id`, `issue_id` and `is_reorder` on orders, plus `title_id` and `creator_id` on statements.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| :--- | :--- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_RESOURCE` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_CREATOR_NOT_FOUND` | 404 |
| `ERR_TITLE_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_ISSUE_NOT_FOUND` | 404 |
| `ERR_STAGE_NOT_FOUND` | 404 |
| `ERR_CATALOG_NOT_FOUND` | 404 |
| `ERR_SOLICITATION_NOT_FOUND` | 404 |
| `ERR_VARIANT_COVER_NOT_FOUND` | 404 |
| `ERR_RETAILER_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_PRINT_RUN_NOT_FOUND` | 404 |
| `ERR_STATEMENT_NOT_FOUND` | 404 |
| `ERR_STALE_TITLE_VERSION` | 412 |
| `ERR_STALE_ISSUE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_RETURNS_NOT_PERMITTED` | 409 |
| `ERR_STATEMENT_ALREADY_PAID` | 409 |
| `ERR_TITLE_NOT_GREENLIT` | 409 |
| `ERR_ASSIGNMENT_NOT_ACCEPTED` | 409 |
| `ERR_CATALOG_NOT_LOCKED` | 409 |
| `ERR_ISSUE_NOT_SOLICITED` | 409 |
| `ERR_RETAILER_NOT_ACTIVE` | 409 |
| `ERR_NOT_CAMERA_READY` | 409 |
| `ERR_PRINT_NOT_COMPLETE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_NON_RETURNABLE_ACK_REQUIRED` | 409 |
| `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` | 409 |
| `ERR_SOLICITATION_WINDOW_CLOSED` | 409 |
| `ERR_CATALOG_DEADLINE_NOT_PASSED` | 409 |
| `ERR_FOC_NOT_REACHED` | 409 |
| `ERR_FOC_ALREADY_PASSED` | 409 |
| `ERR_ON_SALE_DATE_NOT_REACHED` | 409 |
| `ERR_DIGITAL_EMBARGO_VIOLATION` | 422 |
| `ERR_CANNIBALIZATION_WINDOW_CONFLICT` | 409 |
| `ERR_CREATOR_DOUBLE_BOOKED` | 409 |
| `ERR_ON_SALE_CADENCE_CONFLICT` | 409 |
| `ERR_COLLECTED_EDITION_CONFLICT` | 409 |
| `ERR_DUPLICATE_ISSUE_NUMBER` | 409 |
| `ERR_DUPLICATE_VARIANT_CODE` | 409 |
| `ERR_DUPLICATE_SOLICITATION` | 409 |
| `ERR_DUPLICATE_STATEMENT_PERIOD` | 409 |
| `ERR_CATALOG_SLOTS_EXHAUSTED` | 409 |
| `ERR_CRAFT_NOT_SUPPORTED` | 422 |
| `ERR_CRAFT_MISMATCH` | 422 |
| `ERR_TITLE_SCOPE_MISMATCH` | 422 |
| `ERR_VARIANT_RATIO_INVALID` | 422 |
| `ERR_VARIANT_NOT_AVAILABLE` | 422 |
| `ERR_NO_QUALIFYING_ORDERS` | 409 |
| `ERR_NO_ACCEPTED_SOLICITATIONS` | 409 |
| `ERR_STANDARD_COVER_REQUIRED` | 409 |
| `ERR_REQUIRED_CRAFT_STAGES_MISSING` | 409 |
| `ERR_NO_ASSIGNMENT_FOR_CREATOR` | 409 |
| `ERR_ROYALTY_SHARE_POOL_EXCEEDED` | 422 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_ZERO_PAYABLE_STATEMENT` | 422 |
