# Tattoo & Piercing Studio API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Tattoo & Piercing Studio API, the operational backbone of a working body-art studio. The system unifies several activities that, in practice, are frequently scattered across paper waivers, a shared calendar, and a cash drawer: artist portfolios and the booking funnel that feeds them, the non-refundable deposit a client puts down to hold a chair, the dual pricing model (billing either by the hour or at a fixed piece price), the legally significant consent and medical-waiver step, age and identity verification, and the aftercare touch-up policy that governs whether a client returns for free correction work.

The studio runs two parallel intake lanes. Clients may book a piece of **flash** — a pre-drawn design an artist publishes ahead of time — or they may enter an artist's **custom queue**, negotiating a bespoke design through one or more quote-and-revision rounds before any chair is reserved. Both lanes converge on the same appointment lifecycle, which is gated by a strict compliance checkpoint: no session is confirmed unless the client is age-verified, has signed a valid waiver, and has tendered the required deposit. The deposit is non-refundable by design — a client who cancels, no-shows, or reschedules too close to the session forfeits it — but the studio deliberately treats an artist-initiated cancellation differently, preserving the client's money while debiting the artist's reliability standing.

Because the studio's revenue, its artists' payouts, and its compliance posture all depend on getting these rules exactly right, this API treats every appointment as an auditable record. Deposits, gross charges, tax, payouts, reliability scores, and touch-up fees are all computed deterministically from the data on file, so that the studio, its artists, and its clients can each reconstruct any number from first principles.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across the API. The entire surface is mounted under the `/studio` path prefix.

### 2.1. User and Role-Based Access Control

Every request, except those explicitly marked as anonymous, must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request that omits or malforms either header on a protected endpoint is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles, spelled precisely as follows: `StudioManager`, `Artist`, `Client`, and `Anonymous`.

A `StudioManager` is the studio operator. The `StudioManager` role carries an **opaque** identity: when `X-User-Role` is `StudioManager`, the `X-User-ID` is an operator identifier that is not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`. Managers register artists and chairs, approve or reject identity verifications, and schedule or deny touch-ups.

An `Artist` represents a tattoo or piercing artist. The `Artist` role is **entity-backed**: when `X-User-Role` is `Artist`, the `X-User-ID` is the `id` of the acting `Artist`. Ownership checks on any resource that references an `Artist` compare the resource's artist foreign key to `X-User-ID`. Artists publish flash, quote and decline custom work, perform and complete sessions, cancel their own appointments, mark no-shows, and curate their portfolios.

A `Client` represents a studio client. The `Client` role is likewise **entity-backed**: when `X-User-Role` is `Client`, the `X-User-ID` is the `id` of the acting `Client`, and ownership checks on any resource that references a `Client` compare the resource's client foreign key to `X-User-ID`. Clients register, submit ID for verification, hold and book appointments, pay deposits, sign waivers, request custom work, request touch-ups, and reschedule or cancel.

The `Anonymous` role is the unauthenticated self-signup surface and carries an **opaque** identity not tied to any persisted entity. Its sole capability is client self-registration; it is the one role that does not require the authentication headers. The role authorizations for every individual operation are catalogued in §4.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless an endpoint states otherwise, list results are sorted by their `created_at` timestamp in ascending order.

Every list response carries the pagination bookkeeping in the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in the system are full top-level entities that carry a standard set of server-managed fields:

- `id` — a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed at the moment of creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` — an integer that begins at its initial value on creation and increments by one on every mutation. It is the basis for the optimistic concurrency control described in §2.7.

These four fields are present on `Artist`, `Client`, `FlashDesign`, `CustomDesignRequest`, `Appointment`, `Chair`, `Deposit`, `TouchUp`, and `PortfolioItem`.

The `ConsentWaiver` resource is an exception. It is an immutable record of a signature event and therefore carries only `id` and `created_at`; it has neither an `updated_at` nor a `version` field. Its `signed_at` field is a system-set ISO 8601 UTC timestamp recording when the waiver was captured, and it is always equal to the waiver's `created_at`.

### 2.5. State Propagation and Cascading Side Effects

A single operation in this domain frequently mutates more than one resource. Whenever an appointment transition forfeits, applies, or reverses deposits, every affected `Deposit` row is mutated and the appointment's own `deposit_paid_cents` is recomputed accordingly. Whenever a session completion or a cancellation touches an artist's tallies, the relevant counters and the derived `reliability_score` are recomputed on the `Artist`. Every such mutation — on the appointment, on each deposit, on the flash design, on the custom request, and on the artist — independently refreshes that resource's `updated_at` and increments its `version`. The precise cascades for each transition are described in the workflow narratives of §3; the governing principle here is that secondary effects are never silent, and each touched resource carries its own version bump.

### 2.6. Nested Resource Retrieval and Existence Ordering

Many endpoints address a resource through a path that names a parent identifier, and several create child resources whose payloads also reference parents by foreign key. The system validates existence in a strict left-to-right order: path identifiers are resolved first, in the order they appear in the URL, and only then are foreign keys in the request body resolved. The first identifier that does not correspond to an existing resource causes the request to be rejected with `ERR_NOT_FOUND`. For example, a request to list the deposits of a non-existent appointment fails on the appointment before any deposit lookup is attempted.

### 2.7. Optimistic Concurrency Control

Two write operations in this system require the client to prove it is acting on a current view of a parent resource by supplying that parent's last-observed `version`. This guards against a client overwriting a change it has not yet seen.

When holding a new appointment, the request must carry `expected_chair_version`, which must equal the current `version` of the target `Chair`. If a prior hold has legitimately reserved an overlapping slot on that chair and advanced the chair's `version` since the client last read it, the client's view of chair availability is stale; the hold is rejected with `ERR_STALE_VERSION` (HTTP 412). The same field, `expected_chair_version`, is supplied on a reschedule whenever the reschedule moves the appointment to a different chair, and is checked the same way against that chair's current `version`.

When paying a deposit toward an appointment, the request must carry `expected_appointment_version`, which must equal the current `version` of the target `Appointment`. If a prior deposit or a forfeiting reschedule has legitimately mutated the appointment and advanced its `version` since the client last read it, the deposit attempt carries a stale appointment view and is rejected with `ERR_STALE_VERSION` (HTTP 412). Every other write endpoint in the system does not take a version field and performs no concurrency check.

### 2.8. Monetary Values, Rounding, and Time

All monetary amounts in the system are expressed as whole integers of cents. The deposit calculation produces a value rounded up to a whole dollar, that is, to a whole multiple of 100 cents. The tax computed at session completion is rounded half up at the tax step. The commission multiply in the payout computation is likewise rounded half up before any further arithmetic. Where a calculation measures elapsed time, the count of whole days between two instants is taken by flooring to whole days. These precision rules are restated alongside each calculation in §3 so that a reader can reconstruct every amount exactly.

The server maintains a logical UTC clock used for all time-gated decisions — no-show eligibility, reschedule validity, and the touch-up free-window cutoff. An administrative test-driving capability allows the clock to be set to a supplied instant so that time-dependent behavior can be exercised deterministically; this capability accepts a `to_iso8601` value and reports the resulting `current_utc`.

### 2.9. Validation Ordering

When several checks guard the same operation, they are evaluated in a fixed precedence so that the surfaced error is deterministic. Authentication is checked first: a request lacking valid headers fails with `ERR_UNAUTHENTICATED` before anything else. Authorization is checked next: a present but unpermitted role fails with `ERR_FORBIDDEN`. Existence is checked third, resolving path identifiers and then body foreign keys left to right and failing with `ERR_NOT_FOUND`. State validity is checked fourth: an operation requested against a resource that is not in a state permitting the transition fails with `ERR_INVALID_STATE`. Only after these four layers pass does the system evaluate the business-specific safety, constraint, temporal, and fiscal rules described throughout §3, each of which carries its own dedicated error code. Within a single endpoint, the relative ordering of those business rules is stated in the workflow narrative that governs the endpoint.

A malformed body, a missing required field, or a value that is not a member of its declared enumeration is rejected with `ERR_INVALID_REQUEST`. A business-rule violation that has no more specific code — for example, a quote that supplies neither a price nor an hourly rate — is rejected with `ERR_VALIDATION`.

## 3. Business Logic & Workflows

### 3.1. Artists, Chairs, and the Studio's Standing Resources

A `StudioManager` registers an `Artist` by supplying a public `display_name`, a `discipline`, and a default `hourly_rate_cents`. The `discipline` declares the artist's specialty and must be one of `TATTOO`, `PIERCING`, or `BOTH`. The `hourly_rate_cents` is the labor rate, in cents per hour, applied to that artist's hourly-priced sessions, and it must be at least 1000 cents. Two further inputs are optional. The `commission_pct` is the fraction of a session's gross paid out to the artist, with the studio keeping the remainder; it defaults to 0.70 and must be greater than 0 and at most 1. The `accepting_custom` flag declares whether the artist currently takes new entries into their custom queue and defaults to true.

Every artist also carries a set of server-maintained tallies that begin at known values and move only as sessions resolve. The `completed_session_count` starts at 0 and rises by one each time one of the artist's appointments reaches `COMPLETED`. The `artist_cancel_count` starts at 0 and rises by one each time the artist cancels one of their own appointments. The `late_reschedule_count` starts at 0 and rises by one each time one of the artist's appointments is rescheduled inside the forfeiture window. The `reliability_score` starts at 100 and is recomputed — using the strict rule given in §3.9 — whenever a session completes, whenever the artist cancels, and whenever a forfeiting reschedule occurs. Fetching a single artist returns the persisted `reliability_score` together with a second, computed-on-read field, `reliability_score_lenient`, derived by the lenient rule of §3.9 for portfolio display. Artists may be listed, optionally filtered by `discipline`.

A `StudioManager` provisions the physical stations on which work happens. Each `Chair` is created with a human `label` such as "Station 1". An optional `cleanup_buffer_minutes` sets the minimum sanitation gap, in minutes, required between two sessions on that chair; it defaults to 30 and must be at least 0. An optional `active` flag controls whether the chair is in service and bookable; it defaults to true. Chairs may be listed, optionally filtered by `active` status. An inactive chair cannot host a session, and an attempt to hold against one is rejected as a chair-availability failure described in §3.5.

### 3.2. Client Onboarding and Age/Identity Verification

A prospective client registers anonymously through the self-signup surface, supplying their legal `full_name` exactly as it appears on their identity document, an `email`, and a `date_of_birth` as an ISO 8601 date in `YYYY-MM-DD` form. The `email` must be unique across all clients. A newly registered client begins with an `id_status` of `UNVERIFIED`. The `id_document_type` is null until a verification is submitted, and `verified_age_years` is null until verification is approved.

Verification is a small state machine on the client's `id_status`, which moves among `UNVERIFIED`, `PENDING_REVIEW`, `VERIFIED`, and `REJECTED`. The client begins the process by submitting a government ID for review, supplying the `id_document_type`, which must be one of `DRIVERS_LICENSE`, `PASSPORT`, or `STATE_ID`. This submission is permitted only when the client's `id_status` is currently `UNVERIFIED` or `REJECTED`; otherwise it is rejected with `ERR_INVALID_STATE`. On a valid submission the client's `id_document_type` is recorded from the request and `id_status` advances from `UNVERIFIED` to `PENDING_REVIEW`.

From `PENDING_REVIEW`, a `StudioManager` reviews the submission, and the review forks into two branches with divergent outcomes. On approval, the manager moves the client from `PENDING_REVIEW` to `VERIFIED`; this transition is permitted only when the current `id_status` is `PENDING_REVIEW`. Approval is the point at which the age gate is enforced: the client's whole-year age, computed from `date_of_birth` as of the approval date, must be at least the minimum booking age of 18 years. If the client is younger than 18 whole years at the approval date, approval is rejected with `ERR_UNDERAGE`. On a successful approval, `verified_age_years` is set to that whole-year age. On the rejection branch, the manager moves the client from `PENDING_REVIEW` to `REJECTED` — again permitted only from `PENDING_REVIEW` — optionally recording a `reason`, and `verified_age_years` is left null. A rejected client may re-enter the process by submitting again, since submission is allowed from `REJECTED`.

### 3.3. The Flash Lane

An `Artist` publishes a pre-drawn flash piece by supplying the owning `artist_id`, a `title`, a fixed `piece_price_cents`, and an `estimated_minutes`. The `piece_price_cents` is the price, in cents, charged when this flash is tattooed under piece pricing and must be at least 1000 cents. The `estimated_minutes` is the artist's estimate of session length in minutes; it drives both the deposit minimum and the chair-slot length, and must be at least 15. A flash design's `status` follows the availability lifecycle `AVAILABLE`, `RESERVED`, and `RETIRED`, beginning at `AVAILABLE`.

While a flash piece is `AVAILABLE`, it may be retired so that it can no longer be booked; retiring advances `status` from `AVAILABLE` to `RETIRED`, and is permitted only when the piece is not currently `RESERVED`. When a held appointment that references a flash piece is confirmed, that piece transitions from `AVAILABLE` to `RESERVED` (see §3.4). When such an appointment is later cancelled by either party, marked no-show, the reserved flash piece is released back to `AVAILABLE`, as detailed in the cancellation narratives below. An artist's flash catalogue may be listed for a given artist, optionally filtered by `status`.

### 3.4. The Custom Queue

A `Client` enters an artist's bespoke pipeline by submitting a `CustomDesignRequest`, supplying the target `artist_id`, their own `client_id`, and a free-text `brief` describing the desired piece. The request is created in `PENDING`. The `status` of a custom request travels through `PENDING`, `QUOTED`, `REVISION_REQUESTED`, `APPROVED`, `DECLINED`, and `CONVERTED`, where `DECLINED` and `CONVERTED` are terminal. The custom queue for a given artist may be listed, as may custom requests filtered by `client_id`, `artist_id`, or `status`.

An `Artist` prices the work by quoting. A quote is accepted only when the request is in `PENDING` or in `REVISION_REQUESTED`; from either, the request advances to `QUOTED`. The quote must carry an `estimated_minutes` of at least 15 and must supply at least one of `quoted_price_cents` or `quoted_hourly_rate_cents`; when set, each of these must be at least 1000 cents. A quote that supplies neither a price nor an hourly rate is rejected with `ERR_VALIDATION`. On a valid quote the request's `quoted_price_cents`, `quoted_hourly_rate_cents`, and `estimated_minutes` are set from the request; when the source state was `REVISION_REQUESTED`, these fields are overwritten with the new values, supporting repeated negotiation rounds.

From `QUOTED`, the `Client` may bounce the quote back for rework, moving the request from `QUOTED` to `REVISION_REQUESTED`; this then re-opens it for a fresh quote, closing the `QUOTED` → `REVISION_REQUESTED` → `QUOTED` negotiation cycle. Alternatively, from `QUOTED`, the `Client` may accept, moving the request from `QUOTED` to `APPROVED`. An `Artist` may decline a request that is in either `PENDING` or `REVISION_REQUESTED`, moving it to the terminal `DECLINED`. Each of these transitions is permitted only from the stated source state(s); a request to transition from any other state is rejected with `ERR_INVALID_STATE`. Finally, when an `APPROVED` request is consumed by booking an appointment that references it, the request advances from `APPROVED` to the terminal `CONVERTED`, as described in §3.5; this conversion is one-way and is not reversed even if the resulting appointment is later cancelled.

### 3.5. Holding an Appointment

Booking begins by holding a chair. A `Client` creates an appointment hold by supplying the `artist_id`, their `client_id`, the `chair_id`, the `expected_chair_version` (see §2.7), the `pricing_mode`, an `estimated_minutes`, and the session window `start_at` and `end_at`. The session source is supplied as exactly one of `flash_design_id` or `custom_request_id` — these two are mutually exclusive. Pricing inputs `piece_price_cents` and `hourly_rate_cents` accompany the chosen mode. The `pricing_mode` must be one of `HOURLY` or `PIECE`. Both `start_at` and `end_at` are ISO 8601 UTC instants; the session window is treated as the half-open interval from `start_at` up to but not including `end_at`. The `estimated_minutes` must be at least 15 and drives both the deposit minimum and the chair-slot end time. A newly held appointment begins in `HELD`; the appointment `status` travels through `HELD`, `CONFIRMED`, `COMPLETED`, `CANCELLED`, and `NO_SHOW`, of which the last three are terminal.

Creating a hold runs a sequence of checks, each with its own error. **Pricing integrity** comes first among the business constraints: the appointment must specify exactly one of `flash_design_id` or `custom_request_id`, and the pricing fields must match the chosen `pricing_mode`. A `PIECE`-mode session requires `piece_price_cents` (at least 1000 cents when set); an `HOURLY`-mode session requires `hourly_rate_cents` (at least 1000 cents when set), and that hourly rate must be divisible by 4, since the studio bills in quarter-hour increments. Any of these pricing faults — wrong number of sources, missing required price field, or an hourly rate not divisible by 4 — is rejected with `ERR_INVALID_PRICING`. **Custom-request readiness** follows: if a `custom_request_id` is supplied, the referenced custom request must be in `APPROVED`; if it is in any other state the hold is rejected with `ERR_REQUEST_NOT_APPROVED`. **Interval validity** is next: `end_at` must be strictly after `start_at`, failing otherwise with `ERR_INVALID_INTERVAL`. **Artist availability** is then checked: the proposed half-open window from `start_at` to `end_at` must not overlap the window of any other non-terminal appointment for the same `artist_id`; an overlap is rejected with `ERR_ARTIST_DOUBLE_BOOKED`. **Chair availability** is checked next: the chair must be active, and the proposed window — expanded on each side by the chair's `cleanup_buffer_minutes` — must not overlap any other non-terminal appointment on the same `chair_id`; a buffered overlap or an inactive chair is rejected with `ERR_CHAIR_UNAVAILABLE`. Finally the chair-version concurrency check of §2.7 applies, rejecting a stale `expected_chair_version` with `ERR_STALE_VERSION`.

On a successful hold, the system computes the appointment's `required_deposit_cents` (see §3.6 for the formula) and records it, and it advances the held chair's `version` by one so that any concurrent holder's view becomes stale. The appointment's `deposit_paid_cents` begins at 0. An appointment may be fetched individually — returning its computed `deposit_paid_cents`, `required_deposit_cents`, and, once completed, its `gross_cents` and `balance_due_cents` — and appointments may be listed filtered by `artist_id`, `client_id`, `chair_id`, `flash_design_id`, `custom_request_id`, or `status`. Note that booking an appointment against an `APPROVED` custom request consumes the request: the request is moved to `CONVERTED` at confirmation time, not at hold time.

### 3.6. Deposits and the Deposit Minimum

The deposit that holds a chair is non-refundable. A `Client` pays toward an appointment by tendering an `amount_cents` (at least 1 cent) together with the `expected_appointment_version` required by the concurrency rule of §2.7. A deposit may be paid only while the appointment is `HELD` or `CONFIRMED`; an attempt to pay against an appointment in any other state — for instance one already `CANCELLED`, `COMPLETED`, or `NO_SHOW` — is rejected with `ERR_DEPOSIT_NOT_PAYABLE`. A successful payment creates a `Deposit` whose `appointment_id` ties it to the session, whose `amount_cents` records the tender, and whose `status` begins at `CONFIRMED`; a deposit's `status` lifecycle is `CONFIRMED`, `FORFEITED`, and `APPLIED`. Each successful payment adds its `amount_cents` to the appointment's `deposit_paid_cents` and advances the appointment's `version` by one. Deposits for an appointment may be listed, optionally filtered by `status`.

The `required_deposit_cents` recorded at hold time is computed as follows. First an estimate of the session cost is formed: in `PIECE` mode the estimate is simply the `piece_price_cents`; in `HOURLY` mode the estimate is the `estimated_minutes` divided by 60 and rounded up to a whole number of hours, then multiplied by the `hourly_rate_cents`. The raw deposit is that estimate multiplied by the deposit rate of 0.20 (twenty percent). The required deposit is then this single raw figure rounded up to the next whole dollar — that is, divided by 100, rounded up to a whole number, and multiplied back by 100 — giving a whole multiple of 100 cents. This rounding is applied once, to the full estimate after it has been multiplied, never per component.

### 3.7. Consent, Medical Disclosure, and Confirmation

Before any session can run, the client must sign the consent and medical waiver. A `Client` records a `ConsentWaiver` for an appointment by supplying their `client_id`, a `medical_flags` array listing any disclosed medical conditions (for example, `DIABETES` or `BLOOD_THINNER`; an empty array means none disclosed), and an `aftercare_acknowledged` boolean. The waiver is tied to the session through its `appointment_id`. For a waiver to be valid the client must have acknowledged the aftercare instructions, that is, `aftercare_acknowledged` must be true. The waivers a client has signed may be listed, as may the waiver(s) recorded for a particular appointment.

Confirmation is the central compliance checkpoint. A `Client` confirms a `HELD` appointment, and the transition from `HELD` to `CONFIRMED` is permitted only when the appointment is currently `HELD`; otherwise it fails with `ERR_INVALID_STATE`. Three further gates must all pass. The acting client's `id_status` must be `VERIFIED`; if it is not, confirmation is rejected with `ERR_CLIENT_NOT_VERIFIED`. A valid `ConsentWaiver` — one whose `aftercare_acknowledged` is true — must exist for the appointment; if none does, confirmation is rejected with `ERR_WAIVER_MISSING`. The appointment's `deposit_paid_cents` must be at least its `required_deposit_cents`; if the deposit is short, confirmation is rejected with `ERR_DEPOSIT_NOT_MET`. When all gates pass, the appointment advances from `HELD` to `CONFIRMED`. As a side effect, if the appointment references a flash piece, that `FlashDesign` moves from `AVAILABLE` to `RESERVED`; if it instead references a custom request, that `CustomDesignRequest` moves from `APPROVED` to the terminal `CONVERTED`.

### 3.8. Cancellation, No-Show, and Reschedule

The studio distinguishes sharply between who walks away from a confirmed session, and this distinction is the heart of the deposit policy.

When a **client cancels**, the appointment moves to `CANCELLED`; this is permitted from either `HELD` or `CONFIRMED`. Because the deposit is non-refundable, every `CONFIRMED` deposit row on the appointment is moved to `FORFEITED` and the appointment's `deposit_paid_cents` is recomputed to 0. If the appointment held a flash piece, that piece is released from `RESERVED` back to `AVAILABLE`. If the appointment had converted a custom request, that request remains `CONVERTED` — the conversion is one-way and is not undone.

When an **artist cancels** their own appointment, the appointment also moves to `CANCELLED` (permitted from `HELD` or `CONFIRMED`), but the financial and reputational consequences diverge deliberately from a client cancellation. The client's deposits are **not** forfeited: the `CONFIRMED` deposit rows stay `CONFIRMED` and the appointment's `deposit_paid_cents` is preserved so the money can carry forward. Instead, the artist's `artist_cancel_count` is increased by one and their `reliability_score` is recomputed by the strict rule of §3.9. As with any cancellation, if a flash piece was reserved it returns from `RESERVED` to `AVAILABLE`.

When an artist marks a **no-show**, the appointment moves from `CONFIRMED` to `NO_SHOW`; this is permitted only from `CONFIRMED`, and only once the logical clock has reached or passed the appointment's `start_at`. A no-show forfeits the deposit exactly as a client cancellation does: every `CONFIRMED` deposit row becomes `FORFEITED` and `deposit_paid_cents` is recomputed to 0, and any reserved flash piece returns to `AVAILABLE`. The client must pay a fresh deposit to rebook.

A `Client` may **reschedule** a `HELD` or `CONFIRMED` appointment to a new `start_at` and `end_at`, optionally moving it to a different `chair_id` (in which case `expected_chair_version` must accompany the move and is checked per §2.7). The new `start_at` must be strictly after the current clock; otherwise the reschedule is rejected with `ERR_INVALID_INTERVAL`. The appointment's `start_at` and `end_at` are updated to the new window. If the reschedule falls inside the studio's forfeiture window, it is treated as a late reschedule: every `CONFIRMED` deposit row is moved to `FORFEITED`, the appointment's `deposit_paid_cents` is recomputed to 0 (so a fresh deposit becomes required to confirm again), the artist's `late_reschedule_count` is increased by one, and the artist's `reliability_score` is recomputed by the strict rule of §3.9.

### 3.9. Completion, Gross, Balance, Payout, and Reliability

An `Artist` completes a session, moving the appointment from `CONFIRMED` to `COMPLETED`; this is permitted only from `CONFIRMED`. When the session is `HOURLY`, the completion must supply `actual_minutes`, the actual chair time in minutes, which must be at least 1; for a `PIECE` session `actual_minutes` is ignored. Completion computes the session `gross_cents`, then the `balance_due_cents`, applies the deposit, and updates the artist's standing.

**Session gross.** In `PIECE` mode the `gross_cents` is simply the `piece_price_cents`, and the actual time is disregarded. In `HOURLY` mode the studio bills in 15-minute increments: the `actual_minutes` is divided by 15 and rounded up to the next whole increment, and that number of increments is multiplied by the per-increment rate, which is the `hourly_rate_cents` divided by 4. (The hold-time validation guarantees an hourly rate divisible by 4, so this per-increment rate is a whole number of cents.)

**Final balance.** The balance owed at the chair is computed in a pinned order to resolve the interaction between the deposit credit and the tax. First, the pre-tax balance is the session `gross_cents` minus the appointment's `deposit_paid_cents`, but never less than 0 — the non-refundable deposit is consumed first, and any excess of deposit over gross is not returned. Second, the tax is that pre-tax balance multiplied by the tax rate of 0.08 (eight percent), rounded half up to whole cents. Third, the `balance_due_cents` is the pre-tax balance plus that tax. Tax is therefore charged on the post-deposit balance, not on the gross.

As side effects of completion, every `CONFIRMED` deposit row on the appointment is moved to `APPLIED`, the artist's `completed_session_count` is increased by one, and the artist's `reliability_score` is recomputed by the strict rule below.

**Artist reliability.** The reliability score combines an artist's two negative counters. A cancellation penalty is 5 points for each unit of `artist_cancel_count`, and a reschedule penalty is 10 points for each unit of `late_reschedule_count`. The persisted, booking-gating **strict** `reliability_score` is 100 minus both penalties, floored at 0. A separate **lenient** score — surfaced only as the computed-on-read `reliability_score_lenient` for portfolio display — is 100 minus only the cancellation penalty, ignoring late reschedules, likewise floored at 0. The strict score is recomputed on every completion, every artist cancellation, and every forfeiting reschedule.

**Payout.** For a `COMPLETED` appointment, a `StudioManager` or `Artist` may read the payout split. The artist's cut is the session `gross_cents` multiplied by the artist's `commission_pct`, rounded half up to whole cents, then reduced by the flat supply fee of 3500 cents, with the result floored at 0 (the supply fee can never push the cut below zero). The studio's cut is the `gross_cents` minus the artist's cut. The payout read returns `artist_cut_cents`, `studio_cut_cents`, and `gross_cents`.

### 3.10. Aftercare Touch-Ups

After a session is completed, a `Client` may request an aftercare touch-up against it. The touch-up records its `parent_appointment_id` — the original completed session it corrects, a self-reference back into the appointment table — together with a system-set `requested_at` timestamp equal to its `created_at`. A touch-up's `status` lifecycle is `REQUESTED`, `SCHEDULED`, and `DENIED`, beginning at `REQUESTED`. A touch-up may be requested only against a parent appointment that is `COMPLETED`; a request against a parent in any other state is rejected with `ERR_TOUCHUP_PARENT_NOT_COMPLETED`.

The touch-up `fee_cents` is computed at request time by the studio's free-window policy. The number of whole days elapsed is the difference between the request clock and the moment the parent appointment reached `COMPLETED` (its `updated_at` at the instant of completion), expressed in seconds and floored to whole days. The touch-up is free — `fee_cents` of 0 — when it is requested on or before the 90th day, that is, when the elapsed whole days are at most the free window of 90 days, **and** the original session's `ConsentWaiver` had `aftercare_acknowledged` set to true. In every other case — requested after the 90-day free window, or where aftercare was not acknowledged — the `fee_cents` is the studio's flat touch-up fee of 6000 cents.

A `StudioManager` resolves a requested touch-up. Scheduling moves it from `REQUESTED` to `SCHEDULED`, and is permitted only when the touch-up is `REQUESTED` and its parent appointment is `COMPLETED`; a parent that is not `COMPLETED` at schedule time is rejected with `ERR_TOUCHUP_PARENT_NOT_COMPLETED`. Denial moves it from `REQUESTED` to the terminal `DENIED`, permitted only when the touch-up is `REQUESTED`. Touch-ups may be listed for a parent appointment, optionally filtered by `status`, and a single touch-up may be fetched.

### 3.11. Portfolio Curation

An `Artist` showcases finished work by creating a `PortfolioItem`, supplying the owning `artist_id`, the `appointment_id` of the completed session whose work is shown, and a public `caption`. The parent appointment must be `COMPLETED` at creation time. A portfolio item's `visibility` lifecycle is `DRAFT`, `PUBLISHED`, and `HIDDEN`, beginning at `DRAFT`, and `HIDDEN` is terminal. Portfolio items may be listed across the studio, filtered by `appointment_id`, `artist_id`, or `visibility`, and an individual artist's portfolio may be listed on its own.

Publishing moves a portfolio item from `DRAFT` to `PUBLISHED`; it is permitted only when the item is currently `DRAFT` and the linked appointment is `COMPLETED`. Taking an item down moves it from `PUBLISHED` to the terminal `HIDDEN`, permitted only when the item is currently `PUBLISHED`. A transition requested from any other state is rejected with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including the state-transition actions — return a `200 OK` status code. Note that the verification submission, deposit, and waiver endpoints follow this rule precisely: a deposit and a waiver create new resources and return 201, while the verification-submission action modifies the existing client and returns 200.

To reconstruct the full request and response shape of any endpoint, refer back to the workflow narratives in §3; the table below lists only the contract surface.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/studio/artists` | Register an artist | StudioManager |
| GET | `/studio/artists/{id}` | Fetch an artist (includes `reliability_score` and `reliability_score_lenient`) | StudioManager, Artist, Client |
| GET | `/studio/artists` | List artists | StudioManager, Artist, Client |
| GET | `/studio/artists/{id}/flash-designs` | List an artist's flash designs | StudioManager, Artist, Client |
| GET | `/studio/artists/{id}/custom-requests` | List an artist's custom-design queue | StudioManager, Artist |
| GET | `/studio/artists/{id}/portfolio-items` | List an artist's portfolio items | StudioManager, Artist, Client |
| POST | `/studio/clients` | Register a client (self-signup) | Anonymous |
| GET | `/studio/clients/{id}` | Fetch a client | StudioManager, Client |
| GET | `/studio/clients/{id}/waivers` | List the waivers a client has signed | StudioManager, Client |
| POST | `/studio/clients/{id}/id-verification` | Submit a government ID for review | Client |
| POST | `/studio/clients/{id}/id-verification/approve` | Approve the identity/age check | StudioManager |
| POST | `/studio/clients/{id}/id-verification/reject` | Reject the identity/age check | StudioManager |
| POST | `/studio/flash-designs` | Publish a pre-drawn flash design | Artist |
| GET | `/studio/flash-designs/{id}` | Fetch a flash design | StudioManager, Artist, Client |
| POST | `/studio/flash-designs/{id}/retire` | Retire a flash design | Artist |
| POST | `/studio/custom-requests` | Submit a custom design brief | Client |
| GET | `/studio/custom-requests/{id}` | Fetch a custom design request | StudioManager, Artist, Client |
| GET | `/studio/custom-requests` | List custom requests | StudioManager, Artist, Client |
| POST | `/studio/custom-requests/{id}/quote` | Quote a custom request | Artist |
| POST | `/studio/custom-requests/{id}/request-revision` | Bounce a quote back | Client |
| POST | `/studio/custom-requests/{id}/approve` | Accept a quote | Client |
| POST | `/studio/custom-requests/{id}/decline` | Decline a request | Artist |
| POST | `/studio/chairs` | Add a physical station | StudioManager |
| GET | `/studio/chairs/{id}` | Fetch a chair | StudioManager, Artist, Client |
| GET | `/studio/chairs` | List chairs | StudioManager, Artist, Client |
| POST | `/studio/appointments` | Create an appointment hold | Client |
| GET | `/studio/appointments/{id}` | Fetch an appointment | StudioManager, Artist, Client |
| GET | `/studio/appointments` | List appointments | StudioManager, Artist, Client |
| POST | `/studio/appointments/{id}/deposits` | Pay a non-refundable deposit | Client |
| GET | `/studio/appointments/{id}/deposits` | List deposits for an appointment | StudioManager, Artist, Client |
| POST | `/studio/appointments/{id}/waiver` | Record the signed consent/medical waiver | Client |
| GET | `/studio/appointments/{id}/waiver` | List the waiver(s) for an appointment | StudioManager, Artist, Client |
| POST | `/studio/appointments/{id}/confirm` | Confirm a held appointment | Client |
| POST | `/studio/appointments/{id}/cancel` | Client cancels (deposit forfeited) | Client |
| POST | `/studio/appointments/{id}/cancel-by-artist` | Artist cancels (deposit preserved) | Artist |
| POST | `/studio/appointments/{id}/reschedule` | Reschedule an appointment | Client |
| POST | `/studio/appointments/{id}/complete` | Complete a confirmed appointment | Artist |
| POST | `/studio/appointments/{id}/no-show` | Mark a confirmed appointment no-show | Artist |
| GET | `/studio/appointments/{id}/payout` | Read the artist/studio payout split | StudioManager, Artist |
| POST | `/studio/appointments/{id}/touchups` | Request an aftercare touch-up | Client |
| GET | `/studio/appointments/{id}/touchups` | List touch-ups for an appointment | StudioManager, Artist, Client |
| GET | `/studio/touchups/{id}` | Fetch a touch-up | StudioManager, Artist, Client |
| POST | `/studio/touchups/{id}/schedule` | Schedule a requested touch-up | StudioManager |
| POST | `/studio/touchups/{id}/deny` | Deny a requested touch-up | StudioManager |
| POST | `/studio/portfolio-items` | Publish a completed session to portfolio (DRAFT) | Artist |
| GET | `/studio/portfolio-items/{id}` | Fetch a portfolio item | StudioManager, Artist, Client |
| GET | `/studio/portfolio-items` | List portfolio items | StudioManager, Artist, Client |
| POST | `/studio/portfolio-items/{id}/publish` | Publish a draft portfolio item | Artist |
| POST | `/studio/portfolio-items/{id}/takedown` | Take down a published portfolio item | Artist |
| POST | `/studio/_clock/set_current_utc` | Test-driving: set the server's current UTC clock | StudioManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CLIENT_NOT_VERIFIED` | 422 |
| `ERR_UNDERAGE` | 422 |
| `ERR_WAIVER_MISSING` | 422 |
| `ERR_INVALID_PRICING` | 422 |
| `ERR_REQUEST_NOT_APPROVED` | 422 |
| `ERR_INVALID_INTERVAL` | 422 |
| `ERR_ARTIST_DOUBLE_BOOKED` | 409 |
| `ERR_CHAIR_UNAVAILABLE` | 409 |
| `ERR_DEPOSIT_NOT_PAYABLE` | 422 |
| `ERR_DEPOSIT_NOT_MET` | 422 |
| `ERR_TOUCHUP_PARENT_NOT_COMPLETED` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VALIDATION` | 422 |
