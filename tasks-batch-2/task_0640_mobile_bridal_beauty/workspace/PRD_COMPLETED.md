# Mobile & Bridal Beauty API — Product Requirements Document

## 1. Introduction

Wedding-day hair and makeup is a high-stakes, time-boxed service: a single artist (sometimes with an assistant) must finish a whole bridal party on location before the ceremony begins, travelling to the venue, pricing per face, collecting a deposit weeks in advance, and absorbing the chaos of weather and last-minute cancellations. This document specifies the backend API that runs that business end to end — from publishing an artist's portfolio, through quoting and contracting an event, to scheduling the on-location window, billing touch-ups and overtime, and settling refunds when a booking falls through.

The platform is built around a few hard realities. Pricing is computed twice and the two numbers deliberately differ: a forward-looking *estimate* quoted before the party is finalized, and an authoritative *contracted total* locked at signing against a pinned snapshot of the lead artist's rates. Money moves on two independent tracks — a deposit collected up front and a balance collected after the work is done — so an invoice carries two separate status axes that evolve on their own schedules. And because everything is anchored to a wedding date that cannot move, the system reasons about time against a logical server clock, enforces travel buffers between an artist's bookings, and graduates cancellation refunds by how many hours remain before the event.

This API serves three cooperating roles — the platform `Coordinator`, the `Artist`, and the booking-party `Client` — each owning a distinct slice of the workflow. The sections that follow define the global contract (authentication, response envelopes, pagination, precision, concurrency), then the detailed business logic and lifecycles, and finally the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint. The entire API is mounted under the `/bridal-beauty` path prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing or malforming either header is rejected with `ERR_UNAUTHENTICATED`; a header that is absent, empty, or whitespace-only counts as missing, and an `X-User-Role` value that is not exactly one of the three recognized roles counts as malformed and likewise yields `ERR_UNAUTHENTICATED` (not `ERR_FORBIDDEN_ROLE`). When the headers are well-formed — both present and the role one of the three recognized values — but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly three roles: `Coordinator`, `Artist`, and `Client`.

- The `Coordinator` is the platform operator. It owns the artist roster, scheduling, quoting, invoicing visibility, and the logical clock. When `X-User-Role` is `Coordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and record it but does not compare it to any entity's `id`.
- The `Client` is the booking-party lead who owns a bridal event, requests revisions, signs the contract, and pays. When `X-User-Role` is `Client`, `X-User-ID` is likewise an opaque identifier not tied to any persisted entity. Ownership of client-scoped resources is established not by matching `X-User-ID` to an entity `id`, but by comparing `X-User-ID` to the `client_id` recorded on the owning bridal event (see §2.4).
- The `Artist` is a roster artist acting on their own trials, assignments, and portfolio. When `X-User-Role` is `Artist`, `X-User-ID` is the `id` of the acting `Artist` entity; ownership checks on any resource that references an artist (for example, a trial's conducting artist or an assignment's lead artist) compare the resource's artist foreign-key field to `X-User-ID`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items are skipped from the front of the result set and defaults to 0. A `limit` that is non-integer or falls outside `[1, 100]`, or an `offset` that is non-integer or negative, is rejected with `ERR_INVALID_REQUEST`.

Unless an endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order, ties broken by an internal monotonically increasing creation sequence so that two resources created within the same millisecond retain their insertion order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope; `has_more` is `true` exactly when `offset` plus the number of returned items is less than `total_count`.

### 2.4. Common Resource Properties and Identity

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the last modification; it is refreshed on every mutation. The `version` field is an integer that starts at its initial value and increments by one on every mutation of the resource — it backs the optimistic-concurrency mechanism in §2.7.

One entity is the exception: a `Payment` is an immutable record. A `Payment` carries only `id` and `created_at` — it has neither an `updated_at` field nor a `version` field, because it is never modified after it is recorded. Every other entity (`Artist`, `PortfolioItem`, `BridalEvent`, `BookingFace`, `TrialSession`, `Contract`, `ServiceAssignment`, `AddOn`, `Invoice`, `CancellationRecord`) carries the full `id`/`created_at`/`updated_at`/`version` set.

Resource ownership for `Client`-scoped writes is anchored to the bridal event. A bridal event records the `client_id` of the booking-party lead that created it. For any write a `Client` performs against a resource that belongs to an event — requesting a revision, cancelling the event, cancelling a trial, signing a contract, or recording a payment — the system compares the acting `X-User-ID` to the owning event's `client_id`; a mismatch is rejected with `ERR_NOT_EVENT_OWNER`.

### 2.5. Nested Resource Retrieval and Existence Ordering

Several endpoints address a resource through a path identifier, and some list endpoints expose a resource's children (an event's faces, an artist's portfolio, an assignment's add-ons, an invoice's payments). For any request that references resources by path or body identifier, the system validates existence left-to-right in the order the identifiers appear, rejecting with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. A child lookup never runs before its parent has been confirmed to exist. Reverse-reachability list endpoints — for example listing the faces of an event, the portfolio of an artist, the add-ons of an assignment, or the payments of an invoice — first confirm the parent resource exists, then return the children that reference it.

### 2.6. Monetary Precision, Time, and the Logical Clock

All monetary amounts are stored and returned as **integer cents**. Rates, fees, totals, deposits, balances, and refunds are whole numbers of cents; no monetary field carries a fractional cent. Wherever a calculation produces a non-integer cent value — multiplying a rate by a distance, applying a percentage, applying the bride surcharge multiplier, or halving the makeup rate for a touch-up — the result is rounded to a whole cent using the **round-half-up** convention (a value exactly halfway between two whole cents rounds up). The exact point at which rounding is applied is pinned per calculation in §3 and matters: rounding happens on each individual line before lines are summed, never on the final sum alone.

Time is governed by a **logical server clock**. On server startup the clock reads exactly `2026-01-01T00:00:00Z`, and until it is explicitly set it stays at that default and never falls back to wall-clock time. A `Coordinator` may advance the clock by supplying a target instant in the `to_iso8601` field; the response reports the new `current_utc`. Every temporal precondition in this specification — "the clock has reached the trial start", "the window has not started yet", "hours remaining before the event" — is evaluated against this logical clock, referred to throughout as the current time.

### 2.7. Optimistic Concurrency Control

Two write operations guard against acting on a stale view of a bridal event, and they do so by requiring the client to declare the event version it last observed.

Signing a contract requires `expected_event_version` in the request body, carrying the `version` of the target bridal event as the client last read it. If another writer has advanced the event's `version` since then — for instance by re-quoting it, which increments `quote_revision` and bumps the event's `version` — the stale signer's pinned price would reference an outdated quote, so the create is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412).

Scheduling a service assignment likewise requires `expected_event_version` carrying the event `version` the client last observed. If another coordinator has already scheduled the event (advancing it from `CONTRACTED` to `SCHEDULED` and bumping the event's `version`), the current writer's view is stale and a second create would schedule a duplicate on-location window; the request is therefore rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412).

Editing an artist's profile uses the same family of protection but against the artist row: a profile edit requires `expected_artist_version` carrying the artist's last-observed `version`. A missing or non-integer `expected_artist_version` is rejected with `ERR_INVALID_REQUEST`, and a value that does not match the artist's current `version` is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412), the same error used for event-version staleness. No other endpoint takes a version field; an endpoint not named here performs its mutation without any concurrency check.

### 2.8. State Propagation and Cascading Side Effects

Many operations mutate more than one resource. Whenever an operation changes a resource, that resource's `updated_at` is refreshed and its `version` is incremented; this applies equally to a resource changed directly by the request and to any resource the system mutates as a downstream consequence. Cancellation in particular drives multi-hop cascades — settling the invoice, releasing on-location windows, reversing add-ons, voiding the contract, and removing faces — and each entity touched by such a cascade independently advances its own `updated_at` and `version`. Derived totals (`party_size`, `estimated_total_cents`, `contracted_total_cents`, `balance_amount_cents`, `amount_paid_cents`) are recomputed and written back by the operations that affect them, as detailed in §3.

### 2.9. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication is checked first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of every referenced resource left-to-right (`ERR_NOT_FOUND`), then event ownership for client-scoped writes (`ERR_NOT_EVENT_OWNER`), then the optimistic-concurrency event-version check (`ERR_STALE_EVENT_VERSION`), then whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). Only after those guards pass does the system evaluate the operation-specific business rules described in §3 — trial completion, artist eligibility, window conflicts, timeline deadlines, throughput, and fiscal checks. Malformed request bodies — a missing required field, a value outside a declared enum, or an integer below its declared minimum — surface as `ERR_INVALID_REQUEST` (HTTP 400). A request that is well-formed but references a resource that does not exist still yields `ERR_NOT_FOUND`; the body shape is validated as part of request well-formedness.

## 3. Business Logic & Workflows

### 3.1. Building the Roster: Artists and Portfolios

The roster is the foundation of the platform. A `Coordinator` registers an artist by supplying a `display_name`, a `skill_tier` (one of `LEAD`, `SENIOR`, or `JUNIOR`), and the artist's economic profile: a `hair_rate_per_face_cents`, a `makeup_rate_per_face_cents`, and a `travel_rate_per_km_cents`, each a non-negative whole number of cents, plus a `max_faces_per_hour` of at least one, expressing how many faces this artist can finish per on-location hour. An optional `can_assist` flag declares whether the artist may be booked as an assistant on another artist's window; when omitted it defaults to `false`. A newly registered artist begins life with `status` `ACTIVE`. The `status` axis covers `ACTIVE`, `SUSPENDED`, and `RETIRED`. A read-only `portfolio_published` flag, initially `false`, becomes `true` once at least one of the artist's portfolio items has been published.

Only a `Coordinator` may edit an artist. A profile edit may change any of `hair_rate_per_face_cents`, `makeup_rate_per_face_cents`, `travel_rate_per_km_cents`, `max_faces_per_hour`, `status`, or `can_assist`, and must include the `expected_artist_version` concurrency field described in §2.7. A crucial guarantee: editing an artist's rates **never** retroactively touches the rates already pinned into a signed contract — a contract's pinned snapshot is immune to later artist rate edits.

An artist's portfolio is a gallery of showcased looks. A portfolio item is added by either a `Coordinator` or an `Artist` and carries a `look_name`, a `category` (one of `HAIR`, `MAKEUP`, or `BOTH`), and an `artist_id` tying it to its owning artist; it is created in `DRAFT` status. Publishing a portfolio item advances it from `DRAFT` to `PUBLISHED` and, as a side effect, recomputes the owning artist's `portfolio_published` flag — once any published item exists for an artist, that flag reads `true`. Publishing an item that is not in `DRAFT` (for example one already `PUBLISHED`) is rejected with `ERR_INVALID_STATE`.

### 3.2. Opening an Event and Assembling the Party

A bridal event is the anchor around which everything else revolves. A `Client` or `Coordinator` opens one by supplying the `client_id` of the booking-party lead, the `event_date_utc` (the calendar date/time of the wedding), the `ready_by_utc` deadline by which every face must be finished, and the one-way `venue_distance_km` from the artist base to the venue (a non-negative number of kilometers). The `ready_by_utc` must be strictly after the current time and no later than `event_date_utc`; a `ready_by_utc` that violates either bound is rejected with `ERR_INVALID_REQUEST`. An optional `trial_required` flag declares whether the client insists on a completed trial before contracting; it defaults to `true`. The event is created in `DRAFT` status with `estimated_total_cents` at 0, `quote_revision` at 0, and `party_size` at 0. The `status` axis spans `DRAFT`, `QUOTED`, `REVISION_REQUESTED`, `CONTRACTED`, `SCHEDULED`, `COMPLETED`, and `CANCELLED`.

The party is assembled face by face. A `Client` or `Coordinator` adds a booking face to an event by supplying a `person_label` (who the face is, such as `BRIDE` or `BRIDESMAID_1`), a `service_type` (one of `HAIR`, `MAKEUP`, or `BOTH`), and an optional `is_bride` flag that defaults to `false` — bride faces carry a pricing surcharge described in §3.4. Each face records the `event_id` it belongs to. A new face is created in `PENDING` status; its lifecycle covers `PENDING`, `CONFIRMED`, `REMOVED`, and `SERVICED`. Adding a face recomputes the event's `party_size`. Confirming a pending face advances it from `PENDING` to `CONFIRMED`; confirming a face that is not `PENDING` is rejected with `ERR_INVALID_STATE`. Removing a face transitions it to `REMOVED` and again recomputes `party_size`; only a face currently `PENDING` or `CONFIRMED` may be removed, and removing a face in any other state is rejected with `ERR_INVALID_STATE`. Throughout, `party_size` is the count of faces on the event in `PENDING` or `CONFIRMED` status — removed and serviced faces do not count toward it.

### 3.3. Quoting and the Revision Loop

Once at least one face exists, a `Coordinator` issues a quote, advancing the event from `DRAFT` to `QUOTED`. Quoting is permitted only when the event has at least one booking face in `PENDING` or `CONFIRMED` status and the `ready_by_utc` deadline is still in the future relative to the current time; a quote attempted with no qualifying face, or one whose `ready_by_utc` deadline has passed, is rejected with `ERR_INVALID_STATE`. The `ready_by_utc`-in-the-future precondition is enforced only on the initial `DRAFT → QUOTED` quote, not on a re-quote from `REVISION_REQUESTED`. Issuing the quote runs the estimate calculation (see §3.4) and writes the result into `estimated_total_cents`, increments `quote_revision` by one, and sets `party_size` to the count of faces in `PENDING` or `CONFIRMED` status.

A `Client` who is unhappy with a quote may request a revision, moving the event from `QUOTED` to `REVISION_REQUESTED`. This is permitted only when the acting client owns the event (a non-owner is rejected with `ERR_NOT_EVENT_OWNER`), the event is currently `QUOTED` (any other state is rejected with `ERR_INVALID_STATE`), and no signed contract yet exists for it (a signed contract is likewise rejected with `ERR_INVALID_STATE`); the side effect is to clear `estimated_total_cents` back to 0. From `REVISION_REQUESTED`, the `Coordinator` re-quotes — the same quote action, now advancing `REVISION_REQUESTED` back to `QUOTED` — which again requires at least one `PENDING` or `CONFIRMED` face, recomputes and resets `estimated_total_cents`, increments `quote_revision` by one, and recomputes `party_size`. The loop `QUOTED → REVISION_REQUESTED → QUOTED` may cycle any number of times, and `quote_revision` counts the rounds.

### 3.4. Pricing: The Forward-Looking Estimate vs. the Contracted Baseline

The platform prices an event twice, and the two figures are computed against deliberately different inputs.

The **estimate** is forward-looking and is produced whenever a quote is issued. It counts every face the client might bring — those in `PENDING` *or* `CONFIRMED` status — because before any face is confirmed the estimate should reflect the largest plausible party. The quoting artist for the estimate is chosen by a selector: among artists whose `status` is `ACTIVE` and whose `skill_tier` is `LEAD`, the system picks the cheapest, ranked by the sum of `hair_rate_per_face_cents` and `makeup_rate_per_face_cents` ascending; ties are broken by `created_at` ascending (the earliest-created wins). If no `ACTIVE` `LEAD` artist exists on the roster, the quote is rejected with `ERR_NO_LEAD_ARTIST`. For each counted face, a per-face base begins at zero; if the face's `service_type` is `HAIR` or `BOTH`, the artist's `hair_rate_per_face_cents` is added, and if it is `MAKEUP` or `BOTH`, the `makeup_rate_per_face_cents` is added. If the face is a bride, that per-face base is multiplied by the bride surcharge multiplier of 1.5 and rounded half-up to a whole cent before being added to the running per-face subtotal — this per-line rounding happens on each bride line individually. The travel fee is the selected artist's `travel_rate_per_km_cents` multiplied by the event's `venue_distance_km`, rounded half-up to a whole cent. The `estimated_total_cents` is the sum of the per-face subtotal and the travel fee.

The **contracted total** is the authoritative, final baseline and is computed at signing. It differs from the estimate in two ways: it counts only `CONFIRMED` faces (pending faces are excluded), and it prices them at the lead artist's *pinned* rates rather than the cheapest-lead selector. For each `CONFIRMED` face, the per-face base starts at zero; `pinned_hair_rate_cents` is added when the `service_type` is `HAIR` or `BOTH`, and `pinned_makeup_rate_cents` is added when it is `MAKEUP` or `BOTH`. A bride face's base is multiplied by the same 1.5 surcharge multiplier and rounded half-up to a whole cent on that line. The travel fee is `pinned_travel_rate_per_km_cents` multiplied by `venue_distance_km`, rounded half-up to a whole cent. The `contracted_total_cents` is the sum of the per-face subtotal and the travel fee. Because it excludes pending faces and uses pinned rather than cheapest-lead rates, the contracted total will generally differ from the `estimated_total_cents` the client saw at quote time.

### 3.5. The Trial Session

Many clients insist on a trial run before committing. A trial session is booked by a `Coordinator` or `Client` against a specific `event_id` and `artist_id` (existence validated in that left-to-right order — the `event_id` first, then the `artist_id`), with a `start_utc` and `end_utc` defining the window (`end_utc` must be strictly after `start_utc`, otherwise `ERR_INVALID_REQUEST`) and a flat `trial_fee_cents` of at least zero. A new trial is created in `BOOKED` status; its lifecycle covers `BOOKED`, `COMPLETED`, `NO_SHOW`, and `CANCELLED`. At booking time the system enforces that the trial window, treated as the half-open interval from `start_utc` up to but not including `end_utc`, does not overlap any other non-terminal trial of the same artist; two windows that merely touch end-to-start are allowed, but any genuine overlap is rejected with `ERR_TRIAL_WINDOW_CONFLICT`.

The conducting `Artist` marks a trial completed, advancing `BOOKED` to `COMPLETED`, but only when the acting artist is the trial's own artist and the current time has reached the trial's `start_utc`; an artist other than the trial's own artist is rejected with `ERR_FORBIDDEN_ROLE`, and an attempt before the current time reaches `start_utc` is rejected with `ERR_INVALID_STATE`. A `Coordinator` may record a no-show, advancing `BOOKED` to `NO_SHOW`, but only once the current time has reached the trial's `end_utc`; an attempt before then is rejected with `ERR_INVALID_STATE`. A `Client` may cancel a trial, advancing `BOOKED` to `CANCELLED`, provided the acting client owns the event the trial belongs to (a non-owning client is rejected with `ERR_NOT_EVENT_OWNER`); cancelling releases the artist's reserved window so it no longer blocks other bookings.

### 3.6. Contracting: Pinning Rates and Opening the Invoice

Signing a contract is the pivot from negotiation to commitment, and it is a `Client`-only action that moves the event from `QUOTED` to `CONTRACTED`. The request supplies the `event_id`, the chosen `lead_artist_id`, and the `expected_event_version` concurrency token. Several conditions must hold, evaluated after the §2.9 guards. The acting client must own the event. The parent event must currently be `QUOTED`; signing from any other state is rejected with `ERR_INVALID_STATE`. If the event's `trial_required` flag is set, a trial session for this event must already be in `COMPLETED` status — otherwise the sign is rejected with `ERR_TRIAL_NOT_COMPLETED`. The nominated lead artist must have `status` `ACTIVE`; a non-active lead is rejected with `ERR_ARTIST_NOT_ACTIVE`. The event must have at least one `CONFIRMED` booking face — this check runs after the artist-active check, and an event with no `CONFIRMED` face is rejected with `ERR_INVALID_STATE`. And the supplied `expected_event_version` must match the event's current `version`, or the sign is rejected with `ERR_STALE_EVENT_VERSION`.

When all conditions pass, the contract is created already in `SIGNED` status (its lifecycle is `DRAFT`, `SIGNED`, `VOIDED`, where `DRAFT` is the conceptual pre-persist state). At signing the system snapshots the lead artist's three rates into `pinned_hair_rate_cents`, `pinned_makeup_rate_cents`, and `pinned_travel_rate_per_km_cents`, immune to any later edit of the artist's live rates. It then runs the contracted-total calculation over the `CONFIRMED` faces to set `contracted_total_cents`, and runs the deposit split (see §3.7) to set `deposit_due_cents`. As the first cascade hop, signing auto-opens an invoice for the event with `deposit_status` `DUE` and `balance_status` `NOT_DUE`. Signing also increments the event's `version` by one, advancing the event to `CONTRACTED`.

### 3.7. The Deposit Split

The deposit owed up front is a tiered percentage of the contracted total, keyed on which tier the total falls into. Let the contracted total be the value just computed. If it is below 50,000 cents, the deposit percentage is 25 percent. If it is at least 50,000 cents but below 200,000 cents, the percentage is 30 percent. If it is 200,000 cents or more, the percentage is 40 percent. The tier boundaries are half-open from below: a contracted total of exactly 50,000 cents falls in the middle (30 percent) tier, and exactly 200,000 cents falls in the top (40 percent) tier. The `deposit_due_cents` is the contracted total multiplied by the chosen percentage, rounded half-up to a whole cent.

### 3.8. The Invoice and Its Two Independent Axes

When a contract is signed the system opens an invoice, recording the `event_id` it bills and the `contract_id` whose baseline it draws on. The invoice copies the contract's `deposit_due_cents` into its own `deposit_amount_cents` at open, sets its running `balance_amount_cents` to the contract's full `contracted_total_cents` at open (no payments or add-ons yet recorded), and tracks `amount_paid_cents` (the sum of successfully recorded payments), which opens at 0. Two status axes evolve independently on the same invoice row. The `deposit_status` axis runs `DUE → PAID → REFUNDED` or `DUE → PAID → FORFEITED`. The `balance_status` axis runs `NOT_DUE → DUE → PAID` or `NOT_DUE → DUE → WRITTEN_OFF`. An invoice opens with `deposit_status` `DUE` and `balance_status` `NOT_DUE`.

The running balance is reconciled on every successful payment, every add-on creation or reversal, every assignment cancellation, and every event cancellation. The reconciliation works as follows: sum the `amount_cents` of all `APPLIED` add-ons across the event's assignments; sum the `amount_cents` of all `SUCCEEDED` payments on the invoice; the gross amount due is the contract's `contracted_total_cents` plus the applied add-ons; the `balance_amount_cents` is the gross due minus the paid total minus any cancellation relief that has been written off, floored at zero so the balance is never negative; and `amount_paid_cents` is set to the paid total. Once at least one add-on has been applied, the reconciled balance includes those add-on amounts and therefore diverges from the bare contracted baseline.

### 3.9. Payments: Settling Deposit, Then Balance

A `Client` records a payment against an invoice by supplying which installment it targets in `applies_to` (either `DEPOSIT` or `BALANCE`) and an `amount_cents` of at least one cent. A recorded payment carries the `invoice_id` it applies to and is always settled with `outcome` `SUCCEEDED` — there is no other outcome. Each payment runs the balance reconciliation and advances the relevant status axis. Only the owning client may pay; the ownership check compares the acting identity to the owning event's `client_id`.

A deposit payment must settle the deposit exactly. Its `amount_cents` must equal the `deposit_amount_cents` minus any deposit already paid; an amount over or under that exact remaining deposit is rejected with `ERR_DEPOSIT_AMOUNT_MISMATCH`. A successful, exact deposit payment advances `deposit_status` from `DUE` to `PAID`, increments `amount_paid_cents`, and recomputes `balance_amount_cents`.

A balance payment is gated only on the deposit having settled first and on not overpaying — it is not separately gated on `balance_status` already being `DUE`: attempting to pay the balance while `deposit_status` is anything other than `PAID` is rejected with `ERR_DEPOSIT_NOT_SETTLED` (this deposit-settled check is evaluated before the overpay check). A balance payment may not exceed the current `balance_amount_cents`; an overpayment is rejected with `ERR_BALANCE_OVERPAY`. The balance axis only becomes collectible — `balance_status` moving from `NOT_DUE` to `DUE` — as a system side effect when a service assignment reaches `COMPLETED` while the deposit is already `PAID`. A balance payment that clears the balance (so the post-payment `balance_amount_cents` is zero) advances `balance_status` to `PAID` (from `DUE` on the normal path, or from whatever value it then holds), increments `amount_paid_cents`, and sets `balance_amount_cents` to zero; a partial balance payment that does not clear the balance leaves `balance_status` unchanged.

### 3.10. Scheduling the On-Location Window

With a signed contract and a paid deposit in hand, a `Coordinator` schedules the on-location service window, advancing the event from `CONTRACTED` to `SCHEDULED`. The request supplies the `event_id`, the lead `artist_id`, an optional `assistant_artist_id` (null when the artist works solo), the `window_start_utc` and `window_end_utc` of the on-location window (`window_end_utc` must be strictly after `window_start_utc`), and the `expected_event_version` concurrency token. The assignment is created in `SCHEDULED` status — its lifecycle is `SCHEDULED`, `IN_PROGRESS`, `COMPLETED`, `CANCELLED` — and records `faces_committed`, the count of `CONFIRMED` faces on the event at scheduling time. Its `extended_until_utc` field is null until an extended-stay add-on extends it.

Scheduling has a chain of preconditions beyond the §2.9 guards. The owning event must be `CONTRACTED`; scheduling from any other state is rejected with `ERR_INVALID_STATE`. A signed contract must exist for the event, and the invoice's `deposit_status` must be `PAID`; each of those two unmet preconditions is likewise rejected with `ERR_INVALID_STATE`. The supplied `window_end_utc` must be strictly after `window_start_utc`, or the request is rejected with `ERR_INVALID_REQUEST`. The supplied `expected_event_version` must match the event's current `version`, failing with `ERR_STALE_EVENT_VERSION` (this version check is evaluated before the state, contract, and deposit checks). Both the lead artist and, when present, the assistant must have `status` `ACTIVE`, failing with `ERR_ARTIST_NOT_ACTIVE`. When an `assistant_artist_id` is supplied it must reference an artist whose `can_assist` is `true` and must not be the same artist as the lead, failing with `ERR_INVALID_ASSISTANT`. The window must respect each involved artist's travel buffer (see §3.11). The window's `window_end_utc` must be no later than the event's `ready_by_utc` so the faces finish by the timeline deadline; a window ending past the deadline is rejected with `ERR_WINDOW_PAST_DEADLINE`. And the combined throughput of the lead plus optional assistant must cover the `CONFIRMED` face count over the window (see §3.12). On success the assignment is created, `faces_committed` is set to the count of `CONFIRMED` faces, the event advances to `SCHEDULED`, and the event's `version` is incremented by one.

### 3.11. The Travel Buffer Between Windows

Because an artist must physically travel between venues, the system reserves a 60-minute travel buffer around every assignment window. When scheduling a window for an artist — whether that artist is acting as the lead or as the assistant — the system takes the new window's interval, expands it by 60 minutes on each side, and rejects the schedule if that expanded interval intersects any of that artist's existing non-cancelled assignment windows (any assignment whose `status` is not `CANCELLED`). Put concretely: an existing window, treated as the half-open interval from its start up to but not including its end, blocks a new window whenever the new window's interval expanded by 60 minutes before its start and 60 minutes after its end intersects the existing interval. Two windows separated by exactly the 60-minute gap are adjacent and allowed; anything closer is rejected with `ERR_ASSIGNMENT_WINDOW_CONFLICT`. This buffer check considers both the lead and the assistant identities of the new assignment against all of their respective prior windows.

### 3.12. Throughput: Can the Window Hold the Party?

A booking only makes sense if the assigned artists can actually finish every confirmed face inside the window. The required throughput is computed from the count of `CONFIRMED` faces on the event and the combined hourly capacity of the assigned artists. The lead artist contributes its `max_faces_per_hour`; the assistant, when present, contributes its own `max_faces_per_hour`, and when absent contributes zero. The window length in hours is the span from `window_start_utc` to `window_end_utc` expressed in hours. The capacity is the combined faces-per-hour of lead plus assistant multiplied by that window length in hours, then floored to a whole number of faces (a partial hour does not buy a partial face). The window is sufficient when this floored capacity is greater than or equal to the `CONFIRMED` face count; if the capacity equals the confirmed count exactly, the window passes, but if it falls even one face short the schedule is rejected with `ERR_INSUFFICIENT_THROUGHPUT`.

### 3.13. Running the Window: Start, Add-Ons, Complete

On the day, the assigned `Artist` starts the window, advancing the assignment from `SCHEDULED` to `IN_PROGRESS`, but only when the acting artist is the assignment's lead artist, the current time has reached `window_start_utc`, and the owning event is in `SCHEDULED` status. An acting artist other than the assignment's lead is rejected with `ERR_FORBIDDEN_ROLE`; an attempt before the current time reaches `window_start_utc`, or while the owning event is not `SCHEDULED`, is rejected with `ERR_INVALID_STATE`.

During the window, a `Coordinator` or `Artist` may apply add-ons to an assignment; the system does not gate add-on creation on the assignment's state, so an add-on may be applied to an assignment in any state. An add-on declares its `addon_type` — `TOUCH_UP` or `EXTENDED_STAY` — and a `quantity` of at least one, records the `assignment_id` it extends, and is created in `APPLIED` status (its lifecycle is `APPLIED`, `REVERSED`). A `TOUCH_UP` quantity is a number of touch-up faces; an `EXTENDED_STAY` quantity is a number of extra 30-minute blocks. The add-on's billed `amount_cents` is computed as follows. For a `TOUCH_UP`, the per-touch-up unit price is the assignment's lead artist's current (live, not contract-pinned) `makeup_rate_per_face_cents` multiplied by one half and rounded half-up to a whole cent; that rounded per-unit price is then multiplied by the quantity to give `amount_cents` (rounding is applied to the unit before multiplying by quantity). For an `EXTENDED_STAY`, each extra 30-minute block is billed at a flat overtime rate of 8,000 cents, so `amount_cents` is 8,000 multiplied by the quantity; in addition, the assignment's `extended_until_utc` is set to its `window_end_utc` pushed out by the quantity times 30 minutes. An `EXTENDED_STAY` add-on may not push `extended_until_utc` past the event's `ready_by_utc`; a request that would extend beyond the deadline is rejected with `ERR_EXTENSION_PAST_DEADLINE`. Applying any add-on runs the balance reconciliation so the invoice's `balance_amount_cents` reflects the new charge.

The assigned `Artist` completes the window, advancing the assignment from `IN_PROGRESS` to `COMPLETED`, only when the acting artist is the assignment's lead artist and every add-on on the assignment is in a settled state — that is, each add-on is either `APPLIED` or `REVERSED`, with none left pending. An acting artist other than the assignment's lead is rejected with `ERR_FORBIDDEN_ROLE`, and a complete attempted on an assignment that is not `IN_PROGRESS` is rejected with `ERR_INVALID_STATE`. Completing the assignment has a bubble-up side effect on billing: if the invoice's `balance_status` is currently `NOT_DUE`, it advances to `DUE`, making the balance collectible (this readiness advance is conditioned on the deposit already being `PAID`).

### 3.14. Cancelling an Assignment

A `Coordinator` may cancel a service assignment from either `SCHEDULED` or `IN_PROGRESS`, provided the owning event is not already `COMPLETED`. An assignment that is not in `SCHEDULED` or `IN_PROGRESS`, or whose owning event is already `COMPLETED`, is rejected with `ERR_INVALID_STATE`. Cancelling releases the artist's window (so it no longer blocks future bookings via the travel buffer), reverses every `APPLIED` add-on on that assignment to `REVERSED`, and re-runs the balance reconciliation so the invoice's `balance_amount_cents` drops by the reversed add-on charges. Both the `SCHEDULED → CANCELLED` and `IN_PROGRESS → CANCELLED` transitions perform this same window-release, add-on-reversal, and balance-recompute cascade.

### 3.15. Completing the Event

A `Coordinator` completes an event, advancing it from `SCHEDULED` to `COMPLETED`, only when at least one service assignment exists and every service assignment on the event is in `COMPLETED` status and the invoice's `balance_status` is `PAID`. An event that is not `SCHEDULED`, that has no assignment or any non-`COMPLETED` assignment, or whose invoice `balance_status` is not `PAID`, is rejected with `ERR_INVALID_STATE`. Completing the event transitions every `CONFIRMED` booking face to `SERVICED`. `COMPLETED` is a terminal event state.

### 3.16. Cancellation and the Refund Tiers

A `Client` may cancel an event from `DRAFT`, `QUOTED`, `CONTRACTED`, or `SCHEDULED`, supplying a `reason` (one of `CLIENT_CHOICE`, `WEATHER`, or `ARTIST_UNAVAILABLE`); only the owning client may cancel, and an event in a state outside that set is rejected with `ERR_INVALID_STATE`. Every cancellation produces a cancellation record recording the `event_id`, the `reason`, the computed `hours_before_event` (a fractional number of hours), the resolved `refund_tier`, and the resulting `deposit_refund_cents` and `balance_relief_cents`. Although it mints a new cancellation record, this operation responds with HTTP 200 (not 201) and returns that cancellation record as its `data`, rather than the cancelled event. The depth of the cascade depends on how far the event had progressed.

Cancelling a `DRAFT` or `QUOTED` event is clean: no money has moved and no contract exists, so the cancellation record is created at the `FULL_REFUND` tier with no settlement cascade.

Cancelling a `CONTRACTED` or `SCHEDULED` event runs the **cancellation settlement** and cascades. The settlement first resolves the tier. The hours remaining are the event's `event_date_utc` minus the current time, expressed in hours and allowed to be fractional. If the `reason` is `WEATHER`, the tier is always `FULL_REFUND` regardless of how many hours remain — weather is always fully forgiven, which is what makes a weather cancellation diverge from a `CLIENT_CHOICE` cancellation at identical hours. Otherwise, if the hours remaining are at least 720 (that is, 30 days or more before the event), the tier is `FULL_REFUND`; if the hours remaining are at least 72 but less than 720 (between three and thirty days out), the tier is `DEPOSIT_FORFEIT`; and if fewer than 72 hours remain, the tier is `FULL_FORFEIT`. The lower bounds are inclusive: exactly 720 hours resolves to `FULL_REFUND`, and exactly 72 hours resolves to `DEPOSIT_FORFEIT`.

The money then moves by tier. Under `FULL_REFUND`, `deposit_refund_cents` equals the invoice's `deposit_amount_cents` when the deposit was `PAID` (and zero otherwise), and `balance_relief_cents` equals the entire outstanding `balance_amount_cents`, which is forgiven. Under `DEPOSIT_FORFEIT`, `deposit_refund_cents` is zero (the platform keeps the deposit) and `balance_relief_cents` is the whole outstanding balance, forgiven. Under `FULL_FORFEIT`, `deposit_refund_cents` is zero and `balance_relief_cents` is the whole outstanding balance written off, with the deposit kept and any unpaid balance forfeited to the platform as liquidated damages.

These settled amounts drive the invoice's two axes as a cascade hop. When the resolved tier is `FULL_REFUND` and the deposit was `PAID`, the `deposit_status` advances from `PAID` to `REFUNDED` with the deposit returned. When the tier is `DEPOSIT_FORFEIT` or `FULL_FORFEIT` and the deposit was `PAID`, the `deposit_status` advances from `PAID` to `FORFEITED` with `deposit_refund_cents` of zero. If the deposit had not been `PAID` at cancellation, the `deposit_status` is left unchanged (it stays `DUE`) and `deposit_refund_cents` is zero regardless of tier. Whenever a positive outstanding balance exists at cancellation, the `balance_status` advances to `WRITTEN_OFF` — from `DUE` if the balance had already become collectible, or directly from `NOT_DUE` when cancelling a `CONTRACTED` event whose balance was not yet due — with `balance_relief_cents` equal to that outstanding balance and `balance_amount_cents` driven to zero. When no outstanding balance remains, the `balance_status` is left unchanged.

The remaining cascade hops depend on progression. Cancelling a `CONTRACTED` event, after settling the invoice, transitions every `CONFIRMED` and `PENDING` booking face to `REMOVED`. Cancelling a `SCHEDULED` event additionally, after settling the invoice, transitions every `SCHEDULED` service assignment to `CANCELLED` (releasing their windows) and transitions every `CONFIRMED` and `PENDING` booking face to `REMOVED`. In both cases the signed contract is voided as a system consequence — a `SIGNED` contract whose owning event transitions to `CANCELLED` moves to `VOIDED` and is no longer billable, the invoice settlement having already been handled by the cancellation calculation.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return a `201 Created` status code. Operations that modify an existing resource — including state transitions and clock advances — return a `200 OK` status code. Event cancellation is the one exception to the create-returns-201 rule: although it mints a cancellation record, it is modelled as a transition on the event and returns `200 OK` (see §3.16). The full request and response semantics for each endpoint are described in the §3 narratives; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/bridal-beauty/artists` | Register a roster artist | Coordinator |
| GET    | `/bridal-beauty/artists/{id}` | Fetch an artist | Coordinator, Artist, Client |
| GET    | `/bridal-beauty/artists` | List artists (filter by status, skill_tier) | Coordinator, Artist, Client |
| PATCH  | `/bridal-beauty/artists/{id}` | Edit artist rates or status | Coordinator |
| POST   | `/bridal-beauty/artists/{id}/portfolio` | Add a portfolio item | Coordinator, Artist |
| POST   | `/bridal-beauty/portfolio/{id}/publish` | Publish a portfolio item | Coordinator, Artist |
| GET    | `/bridal-beauty/artists/{id}/portfolio` | List an artist's portfolio items | Coordinator, Artist, Client |
| POST   | `/bridal-beauty/events` | Create a bridal event | Client, Coordinator |
| GET    | `/bridal-beauty/events/{id}` | Fetch an event with computed totals | Client, Coordinator, Artist |
| GET    | `/bridal-beauty/events` | List events (filter by status, client_id) | Coordinator, Client |
| POST   | `/bridal-beauty/events/{id}/faces` | Add a booking face to an event | Client, Coordinator |
| POST   | `/bridal-beauty/faces/{id}/confirm` | Confirm a pending face | Client, Coordinator |
| POST   | `/bridal-beauty/faces/{id}/remove` | Remove a face from the event | Client, Coordinator |
| GET    | `/bridal-beauty/events/{id}/faces` | List faces of an event | Client, Coordinator, Artist |
| POST   | `/bridal-beauty/events/{id}/quote` | Issue or re-issue a quote | Coordinator |
| POST   | `/bridal-beauty/events/{id}/request-revision` | Request a quote revision | Client |
| POST   | `/bridal-beauty/events/{id}/complete` | Complete the event | Coordinator |
| POST   | `/bridal-beauty/events/{id}/cancel` | Cancel the event | Client |
| GET    | `/bridal-beauty/events/{id}/cancellation` | List the cancellation record(s) of an event | Client, Coordinator |
| POST   | `/bridal-beauty/trials` | Book a trial session | Coordinator, Client |
| GET    | `/bridal-beauty/trials/{id}` | Fetch a trial | Coordinator, Client, Artist |
| GET    | `/bridal-beauty/trials` | List trials (filter by event_id, artist_id, status) | Coordinator, Client, Artist |
| POST   | `/bridal-beauty/trials/{id}/complete` | Mark trial completed | Artist |
| POST   | `/bridal-beauty/trials/{id}/no-show` | Mark trial no-show | Coordinator |
| POST   | `/bridal-beauty/trials/{id}/cancel` | Cancel a trial | Client |
| POST   | `/bridal-beauty/contracts` | Sign a contract for a quoted event | Client |
| GET    | `/bridal-beauty/contracts/{id}` | Fetch a contract | Client, Coordinator |
| GET    | `/bridal-beauty/contracts` | List contracts (filter by event_id, lead_artist_id) | Client, Coordinator |
| POST   | `/bridal-beauty/assignments` | Schedule an on-location service window | Coordinator |
| GET    | `/bridal-beauty/assignments/{id}` | Fetch an assignment | Coordinator, Artist, Client |
| GET    | `/bridal-beauty/assignments` | List assignments (filter by event_id, artist_id, assistant_artist_id, status) | Coordinator, Artist, Client |
| POST   | `/bridal-beauty/assignments/{id}/start` | Start the on-location window | Artist |
| POST   | `/bridal-beauty/assignments/{id}/complete` | Complete the window | Artist |
| POST   | `/bridal-beauty/assignments/{id}/cancel` | Cancel the window | Coordinator |
| POST   | `/bridal-beauty/assignments/{id}/addons` | Apply a touch-up or extended-stay add-on | Coordinator, Artist |
| GET    | `/bridal-beauty/assignments/{id}/addons` | List add-ons of an assignment | Coordinator, Artist, Client |
| GET    | `/bridal-beauty/invoices/{id}` | Fetch an invoice with both status axes | Client, Coordinator |
| GET    | `/bridal-beauty/invoices` | List invoices (filter by event_id, contract_id) | Client, Coordinator |
| POST   | `/bridal-beauty/invoices/{id}/payments` | Record a payment against deposit or balance | Client |
| GET    | `/bridal-beauty/invoices/{id}/payments` | List payments of an invoice (filter by applies_to) | Client, Coordinator |
| POST   | `/bridal-beauty/_clock/set_current_utc` | Set the server logical clock | Coordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NOT_EVENT_OWNER` | 403 |
| `ERR_STALE_EVENT_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TRIAL_NOT_COMPLETED` | 409 |
| `ERR_ARTIST_NOT_ACTIVE` | 409 |
| `ERR_INVALID_ASSISTANT` | 409 |
| `ERR_TRIAL_WINDOW_CONFLICT` | 409 |
| `ERR_ASSIGNMENT_WINDOW_CONFLICT` | 409 |
| `ERR_WINDOW_PAST_DEADLINE` | 422 |
| `ERR_INSUFFICIENT_THROUGHPUT` | 422 |
| `ERR_DEPOSIT_AMOUNT_MISMATCH` | 422 |
| `ERR_BALANCE_OVERPAY` | 422 |
| `ERR_DEPOSIT_NOT_SETTLED` | 409 |
| `ERR_EXTENSION_PAST_DEADLINE` | 422 |
| `ERR_NO_LEAD_ARTIST` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
