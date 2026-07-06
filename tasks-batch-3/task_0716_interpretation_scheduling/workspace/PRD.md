# Interpretation Scheduling API — Product Requirements Document

## 1. Introduction

Hospitals, courts, clinics, and law firms routinely need a qualified human interpreter on short notice, and the matching problem is unforgiving: a cardiology consult needs a medically-certified Spanish interpreter on video in the next ninety seconds, while a deposition three weeks out needs a court-certified Mandarin interpreter onsite for a reserved two-hour block. This API is the connective tissue between those clients and a vetted interpreter pool. It governs the full arc of a language encounter — a client files a request, a coordinator dispatches it to the best-scored eligible interpreter, the interpreter accepts and runs the session, and the platform meters time, prices the encounter against a negotiated rate plan, and rolls the charge into an invoice.

Because the same platform serves both on-demand and scheduled work, it must reconcile two very different temporal models against a single billing and quality engine. On-demand work fulfills immediately and cancels freely until someone connects; scheduled work reserves a future window, enforces non-overlap, and prices late cancellations and no-shows as a fraction of the minimum committed block. Layered on top are the long-running concerns every marketplace eventually grows: interpreter quality scoring, client complaints with a review-and-revert loop, dispute-and-reconcile billing corrections, credit limits, and the automatic deactivation of interpreters who repeatedly fail to show. The sections below specify the contract precisely; the business narrative in Section 3 is where the rules that make this domain hard actually live.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope contracts, and cross-cutting principles that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header — or carrying a malformed one — is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The sole partial exception is the logical-clock control endpoint, which still requires the `PlatformAdmin` role rather than being open.

The system recognizes exactly four roles, spelled precisely as follows: `PlatformAdmin`, `CoordinatorOps`, `ClientAccount`, and `Interpreter`. When an authenticated role is not among those permitted for the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Two of these roles are tied to persisted entities and therefore drive ownership checks. When `X-User-Role` is `ClientAccount`, `X-User-ID` is the `id` of the acting `ClientAccount`; ownership checks on any resource that traces back to a client — a request, the session realized from that request's assignment, or a complaint the client filed — compare the resource's owning client to `X-User-ID`. When `X-User-Role` is `Interpreter`, `X-User-ID` is the `id` of the acting `Interpreter`; ownership checks on an assignment or on the session beneath it compare the assignment's interpreter to `X-User-ID`. A logged-in entity-backed user acting on a resource they do not own is rejected with `ERR_NOT_OWNER` (HTTP 403).

The other two roles are operational and not entity-backed. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but never compares it to any entity's `id`. When `X-User-Role` is `CoordinatorOps`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, recorded but never compared against an entity `id`. These two roles operate the pool, rates, clock, and invoicing on behalf of the whole platform rather than on behalf of a single client or interpreter.

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

List endpoints accept two pagination parameters, `limit` and `offset`. The `limit` parameter defaults to 10, may be no smaller than 1, and may be no larger than 100; the `offset` parameter defaults to 0 and is the count of leading records skipped. All list results are returned in ascending order of `created_at` — the oldest record first — unless an endpoint's narrative explicitly states otherwise. Each list response surfaces `limit`, `offset`, `total_count`, and `has_more` in the `meta` block: `total_count` is the size of the full filtered set before the page window is applied, and `has_more` is true exactly when records remain beyond the current window.

### 2.4. Common Resource Properties and the Logical Clock

Every resource is assigned a server-minted `id` that is a UUID carrying no type prefix. Every resource also records a `created_at` timestamp, an ISO 8601 UTC instant with three fractional digits, fixed at creation. Most resources additionally carry an `updated_at` timestamp, refreshed on every mutation, and an integer `version` that begins at 1 and increments by one on each mutation; together these support change tracking and the concurrency control described below. All entities in this system carry the full set — `id`, `created_at`, `updated_at`, and `version`.

Time in this system is not wall-clock time. The platform runs on a **logical clock** whose startup default is exactly `2026-03-01T00:00:00Z`. Until an administrator explicitly advances it, every read of "now" returns this default instant; the server never falls back to real-world time. An administrator may move the clock forward by supplying a target instant `to_iso8601`. Advancing the clock is how offer expiry, no-show grace windows, and scheduled-window arithmetic are exercised: moving the clock past an offer's deadline causes that offer to be observed as expired on the next read.

### 2.5. Nested Resource Addressing

Several resources are addressed beneath a parent in the URL — an interpreter's certifications and language grants, a session's ratings and encounter reports, and so on. When a path names more than one resource, each is validated left to right, and the first that does not exist produces `ERR_RESOURCE_NOT_FOUND` (HTTP 404). Thus a request for the certifications of a non-existent interpreter fails on the interpreter before the child collection is ever consulted. Separately, when a foreign-key field carried in a request body — for example `client_id`, `language_pair_id`, `interpreter_id`, `session_id`, `assignment_id`, or `request_id` — points at a resource that does not exist, the body-level reference failure is reported as `ERR_FK_NOT_FOUND` (HTTP 422).

### 2.6. Validation Ordering

When several checks could fire on one request, they are evaluated in a fixed precedence so that the surfaced error is deterministic. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of every path-referenced resource (`ERR_RESOURCE_NOT_FOUND`), then resolution of every body foreign key (`ERR_FK_NOT_FOUND`), then well-formedness of the body (`ERR_INVALID_REQUEST`), then whether the target is in a state from which the requested transition is defined (`ERR_INVALID_STATE`), then ownership of the target by the acting entity-backed user (`ERR_NOT_OWNER`). Checks specific to a single operation — qualified-interpreter availability, offer expiry, double-booking, window conflicts, capacity, duplicate rating, credit limit, and stale-version rejection — are evaluated after this common preamble, in the position their workflow narrative describes. The practical consequence is that a malformed body is reported as bad input before any state or ownership concern is consulted, and a caller who is not even authorized never learns whether the target resource exists.

### 2.7. Monetary Precision and Rounding

All monetary amounts are stored and returned as whole integer cents; there are no fractional-cent values anywhere in the system. Where a calculation multiplies a charge by a percentage, the result is rounded to the nearest whole cent using round-half-up (a value ending in exactly half a cent rounds up). Where a calculation converts elapsed time into billable units, the conversion uses ceiling — any partial unit rounds up to the next whole unit — and that ceiling is applied to the time-to-units step **before** any multiplication by a rate. For onsite per-hour work, the flat travel surcharge is added **after** the rate multiplication, never folded into it; this per-line ordering is fixed.

### 2.8. Optimistic Concurrency on Dispatch

Dispatching a request is guarded by optimistic concurrency control. The dispatch operation requires the field `expected_request_version`, carrying the client's last observed `version` of the target `InterpretationRequest`. The server compares this value against the request's current `version`. If they do not match — because another coordinator has already dispatched the request, creating an assignment that legitimately advanced the request to `ASSIGNED` and incremented its `version` — the dispatch is rejected with `ERR_STALE_REQUEST_VERSION` (HTTP 412). This prevents a coordinator working from a stale view from creating a second, competing assignment for a request that has already moved on. Dispatch is the only operation that takes a version field; no other endpoint accepts one.

### 2.9. Fiscal Guardrails

Each `ClientAccount` carries a `credit_limit_cents`, the maximum unpaid invoice balance the client is permitted to accumulate, defaulting to 5,000,000 cents (fifty thousand dollars) when not supplied at creation. Against this sits `outstanding_balance_cents`, a computed figure equal to the sum of `total_cents` across that client's invoices currently in the `ISSUED` (unpaid) state; it starts at 0 and is recomputed every time an invoice is issued or settled. Two operations are gated on this guardrail: filing a new request and issuing an invoice. If either would push `outstanding_balance_cents` above `credit_limit_cents`, it is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402). Independently, a client account may be administratively moved to `SUSPENDED` status; a suspended client attempting to file a request or have one dispatched is rejected with `ERR_CLIENT_SUSPENDED` (HTTP 403). A client's `status` is otherwise `ACTIVE`.

### 2.10. Cascade and Hierarchy Consistency

Many operations in this system touch more than one entity. Whenever a mutation fires, the touched entities have their `updated_at` refreshed and their `version` incremented; the narrative in Section 3 names every secondary entity each operation disturbs, and those secondary mutations carry the same `updated_at`/`version` bookkeeping. Two structural invariants recur. First, an interpreter's `active_load` — the count of that interpreter's assignments whose `lifecycle_status` is `ACCEPTED` or `IN_SESSION` — is recomputed on every assignment transition, and the interpreter's pool `status` is recomputed alongside it. Second, an assignment evolves along two independent dimensions at once: its `lifecycle_status` (the operational arc) and its `billing_status` (the money arc); a transition on one dimension does not implicitly move the other except where Section 3 says so explicitly.

## 3. Business Logic & Workflows

### 3.1. Provisioning the Pool, Clients, and Rates

Before any interpretation can happen, an administrator stands up the static catalog. A client organization is created with its `org_name`, an `org_type` drawn from `HOSPITAL`, `COURT`, `CLINIC`, or `LAW_FIRM`, a `contact_email`, and optionally a `credit_limit_cents`; the account opens in `ACTIVE` status with an `outstanding_balance_cents` of 0. An administrator may later suspend an account, flipping its `status` to `SUSPENDED`.

A **language pair** is registered with a `source_lang` and a `target_lang`, each an ISO 639 code, plus an optional `rare` flag; `rare` defaults to false and influences only fulfillment expectations, never billing. Interpreters are onboarded with a `full_name` and an optional `max_concurrent_load` (defaulting to 1, the most simultaneously active assignments they may hold). A freshly onboarded interpreter begins `AVAILABLE`, with `active_load` of 0, `acceptance_pct` of 100, and `no_show_strikes` of 0; its `rating_avg` is null and `rating_count` is 0 until the first rating lands. An interpreter's pool `status` is one of `AVAILABLE`, `BUSY`, `OFFLINE`, or `DEACTIVATED`, and an interpreter or administrator may toggle availability between `AVAILABLE` and `OFFLINE`.

Two credentials attach to an interpreter. A **certification** records a `tier` of `MEDICAL`, `LEGAL`, or `COURT`, and an `expires_at` instant; it is considered valid only while the logical clock is strictly before `expires_at` and the credential has not been revoked. The `revoked` flag defaults to false; an administrator may revoke a certification, setting `revoked` to true. Separately, a **language grant** — a junction recording an `interpreter_id` and a `language_pair_id` — declares which pairs an interpreter can service. Both certifications and language grants can be listed back from their parent interpreter, and language grants can also be listed filtered by the `language_pair_id` they reference.

Rate plans are the pricing backbone. A rate plan row is created for a specific `client_id`, a `certification_tier` (`MEDICAL`, `LEGAL`, or `COURT`), and a `modality` (`PHONE`, `VIDEO`, or `ONSITE`), and declares a `billing_mode` of either `PER_MINUTE` or `PER_HOUR`. The `rate_cents` is interpreted as cents per minute when the mode is `PER_MINUTE` and cents per hour when the mode is `PER_HOUR`. The `min_block_units` (defaulting to 10) is the minimum billable block — measured in minutes for per-minute plans and in hours for per-hour plans. A `travel_surcharge_cents` (defaulting to 0) is a flat charge applied once per onsite session; it must be 0 for any `PHONE` or `VIDEO` row, and supplying a non-zero surcharge on a non-onsite row is malformed input. Each (`client_id`, `certification_tier`, `modality`) key has at most one current row: creating a new row for an existing key sets the new row's `active` flag to true and flips the prior row's `active` to false, so the latest row always supersedes its predecessor.

### 3.2. Filing a Request and the On-Demand / Scheduled Split

A client files an **interpretation request** naming the `client_id`, the `language_pair_id`, a `modality`, a `required_tier` (the minimum certification tier, one of `MEDICAL`, `LEGAL`, `COURT`), and a `scheduling_mode` of either `ON_DEMAND` or `SCHEDULED`. The request opens in `OPEN` status with a `cancellation_fee_cents` of 0.

The two scheduling modes diverge on the time fields. An `ON_DEMAND` request fulfills immediately and must omit (or leave null) both `window_start` and `window_end`. A `SCHEDULED` request reserves a future window and must supply both `window_start` and `window_end` as ISO 8601 UTC instants, with `window_end` strictly after `window_start`; a window whose end is not strictly later than its start is rejected with `ERR_INVALID_WINDOW` (HTTP 400). Supplying window fields on an on-demand request, or omitting them on a scheduled one, is malformed input rejected with `ERR_INVALID_REQUEST` (HTTP 400) — the same code that guards bad enum members, a rating score outside its allowed band, any missing required field, and a travel surcharge set on a non-onsite rate plan. Filing is also subject to the fiscal and suspension guards of Section 2.9: a suspended client cannot file, and a client already over its credit ceiling cannot file.

Scheduled requests additionally must not collide with the client's own calendar. When a new `SCHEDULED` request is filed, its window — treated as a half-open interval that includes its start instant and excludes its end instant — must not overlap the window of any other `OPEN` or `ASSIGNED` `SCHEDULED` request belonging to the same client. Under half-open semantics, two windows that merely touch at an endpoint (one ending exactly when the next begins) do not conflict; any genuine overlap is rejected with `ERR_CLIENT_WINDOW_CONFLICT` (HTTP 409). Requests can be fetched individually and listed, filterable by client, by language pair, and by status.

### 3.3. Dispatch and Interpreter Selection

A coordinator dispatches an `OPEN` request to move it toward fulfillment. Dispatch carries the optimistic-concurrency field `expected_request_version` described in Section 2.8; it succeeds only when the request is `OPEN`, the owning client is `ACTIVE`, the supplied version matches the request's current `version`, and the selection rule below yields at least one eligible interpreter. On success the platform creates a single **assignment** in `lifecycle_status` `OFFERED` and `billing_status` `UNBILLED`, stamps `offered_at` with the current clock, copies the request's scheduling mode into the assignment's `assignment_type`, moves the request to `ASSIGNED`, and increments the request's `version` by 1.

Selection draws from the pool by a strict eligibility filter, then ranks survivors by a weighted score. An interpreter is **eligible** only if its `status` is `AVAILABLE`, its `active_load` is strictly below its `max_concurrent_load`, it holds a language grant for the request's `language_pair_id`, and it holds a certification at the request's `required_tier` that is neither revoked nor expired (clock strictly before `expires_at`). For a `SCHEDULED` request there is an additional eligibility condition: the interpreter must not be double-booked, meaning the interpreter must not already hold another non-terminal `SCHEDULED` assignment (one whose lifecycle is `OFFERED`, `ACCEPTED`, or `IN_SESSION`) whose request window shares any instant with this request's window under **closed-interval** semantics, where windows that merely touch at an endpoint do conflict. If the eligible set is empty for an ordinary reason, dispatch instead drives the request from `OPEN` to `UNFULFILLABLE` (still incrementing `version` by 1). When dispatch is attempted but no interpreter holds a valid required-tier certification for the language pair, the operation is rejected with `ERR_NO_QUALIFIED_INTERPRETER` (HTTP 409); when the only obstacle is that the otherwise-chosen interpreter's scheduled window collides with one of their existing windows, it is rejected with `ERR_INTERPRETER_DOUBLE_BOOKED` (HTTP 409); and an attempt that would involve a `DEACTIVATED` interpreter is rejected with `ERR_INTERPRETER_DEACTIVATED` (HTTP 409).

Among eligible interpreters, the winner is the one with the highest score. For each candidate, take its rating contribution as `rating_avg` when `rating_count` is greater than 0, and otherwise substitute the default rating of 4.0 (so a brand-new interpreter is not ranked as though it scored zero). The score is the sum of three terms: the rating contribution multiplied by 100 and then by the rating weight of 0.5; plus the candidate's `acceptance_pct` multiplied by the acceptance weight of 0.3; plus the value of one minus the ratio of `active_load` to `max_concurrent_load`, multiplied by 100 and then by the load weight of 0.2. The score is computed to four decimal places. Ties are broken by lowest `active_load` first, and if still tied, by earliest `created_at` — never by `id`.

### 3.4. The Offer Window: Accept, Decline, Expire

An offered assignment is a time-boxed offer. The interpreter who owns it may accept it, but only while the clock is still strictly before `offered_at` plus the offer time-to-live of 120 seconds, and only while their `active_load` remains strictly below `max_concurrent_load`. Accepting moves `lifecycle_status` to `ACCEPTED`, increments the interpreter's `active_load` by 1 — and if that brings `active_load` up to `max_concurrent_load`, flips the interpreter's `status` to `BUSY` — and recomputes the interpreter's `acceptance_pct`. An accept attempted after the offer's deadline is rejected with `ERR_OFFER_EXPIRED` (HTTP 409); an accept that would carry the interpreter to or beyond `max_concurrent_load` is rejected with `ERR_INTERPRETER_AT_CAPACITY` (HTTP 409).

The interpreter may instead decline the offer, moving `lifecycle_status` to `DECLINED`, recomputing `acceptance_pct`, and bubbling the parent request from `ASSIGNED` back to `OPEN` so it can be re-dispatched to someone else. Expiry reaches the same destinations automatically: once the clock passes `offered_at` plus the 120-second offer window, an offered assignment is observed as `EXPIRED`, its expiry recomputes `acceptance_pct`, and the parent request likewise returns from `ASSIGNED` to `OPEN`. The interpreter's `acceptance_pct` is the percentage of offers accepted against the total of accepted, declined, and expired offers, on a 0-to-100 scale, defaulting to 100 when there is no history yet.

### 3.5. Running the Session

With an assignment `ACCEPTED`, the interpreter starts the session — permitted only when no session already exists for that assignment, and, for a `SCHEDULED` assignment, only once the clock has reached `window_start` minus the early-start grace of 300 seconds (interpreters may connect up to five minutes early). Starting creates a **session** in `CONNECTING` status and moves the assignment's `lifecycle_status` to `IN_SESSION`. The owning interpreter then connects, which stamps `connected_at` with the current clock and moves the session to `ACTIVE`.

Ending an active session is where time becomes money. On end, `ended_at` is stamped with the clock, the session-billing calculation runs to set `billed_units` and `billed_amount_cents`, and the session moves to `ENDED`. Completing the session then bubbles upward: the assignment moves `lifecycle_status` from `IN_SESSION` to `COMPLETED` with `billing_status` set to `BILLABLE`, the interpreter's `active_load` decrements by 1 (and if the interpreter had been `BUSY`, its `status` returns to `AVAILABLE`), and the parent request moves from `ASSIGNED` to `FULFILLED`.

**Session billing** prices the encounter against the effective rate plan — the single `active` rate plan row whose client, certification tier, and modality match the request's `client_id`, `required_tier`, and `modality`. If no such active row exists when billing must run, the operation is rejected with `ERR_NO_RATE_PLAN` (HTTP 409). The duration is the number of seconds between `connected_at` and `ended_at`. For a per-minute plan, divide the duration in seconds by 60 and round up to the next whole minute to get the raw units, then take the larger of that figure and the plan's `min_block_units`; the charge is that number of billed units multiplied by `rate_cents`, and no travel surcharge is ever added. For a per-hour plan, divide the duration in seconds by 3600 and round up to the next whole hour to get the raw units, then take the larger of that figure and the plan's `min_block_units`; the charge is that number of billed units multiplied by `rate_cents`, plus — and only when the modality is `ONSITE` — the plan's `travel_surcharge_cents` added once after the multiplication. In both modes the time-to-units rounding-up happens before the multiply, and `billed_units` holds the final whole-unit count.

### 3.6. No-Shows and Interpreter Deactivation

When a party fails to appear, a coordinator records it against a `CONNECTING` session, naming the `party` as either `CLIENT` or `INTERPRETER`; any other value is rejected with `ERR_INVALID_NO_SHOW_PARTY` (HTTP 400). A no-show may only be recorded once the clock has reached the relevant start instant — the scheduled start for a scheduled engagement, or the offer-accept moment for an on-demand one — plus the no-show grace of 600 seconds.

A **client no-show** moves the session to `CLIENT_NO_SHOW`, runs the no-show fee calculation, writes the result onto the request's `cancellation_fee_cents`, and sets the assignment's `billing_status` to `BILLABLE` so the client is charged. The no-show fee is the estimated minimum charge multiplied by the no-show percentage of 0.50 (fifty percent), rounded half-up to whole cents. The **estimated minimum charge** is the effective plan's `min_block_units` multiplied by its `rate_cents`, plus the plan's `travel_surcharge_cents` once when the modality is `ONSITE`. An **interpreter no-show** instead moves the session to `INTERPRETER_NO_SHOW`, levies no client charge (the fee is 0 and the assignment's `billing_status` is set to `WAIVED`), and increments the interpreter's `no_show_strikes` by 1. Either way, the no-show completes the engagement: the assignment moves `IN_SESSION` to `COMPLETED`, and the request moves `ASSIGNED` to `FULFILLED`.

Interpreter no-shows carry a compounding consequence. When an interpreter's `no_show_strikes` reaches the deactivation threshold of 3, the platform sets that interpreter's `status` to `DEACTIVATED` and resets its `active_load`. That deactivation cascades further: every other still-offered assignment the interpreter holds is moved to `lifecycle_status` `CANCELLED`, and each such cancellation in turn bubbles its own parent request from `ASSIGNED` back to `OPEN` so those requests can be re-dispatched to other interpreters.

### 3.7. Cancellation and Its Fee Bands

A client may cancel their own request while it is `OPEN` or `ASSIGNED`, provided — when `ASSIGNED` — the session beneath it has not yet reached `ACTIVE`. Cancellation runs the cancellation-fee calculation, writes the outcome to `cancellation_fee_cents`, and moves the request to `CANCELLED`. If an assignment was outstanding (offered or accepted), it cascades to `lifecycle_status` `CANCELLED`; when a late fee applies the assignment's `billing_status` is set to `BILLABLE`, and otherwise it is set to `WAIVED`. The cascade also decrements the interpreter's `active_load` by 1, and if the interpreter had been `BUSY` at the moment its load returns to availability, its `status` returns to `AVAILABLE`.

The fee itself depends on scheduling mode and lead time. For an `ON_DEMAND` request the fee is always 0 — on-demand work cancels free, and the only thing that closes that free window is a session reaching `ACTIVE`, not any clock arithmetic. For a `SCHEDULED` request, compute the lead time as `window_start` minus the current clock. If the lead time is at least the late-cancel window of 7,200 seconds (two hours) — that is, the client cancelled with two or more hours to spare — the fee is 0. If the lead time is between zero and the late-cancel window (zero inclusive, the two-hour mark exclusive), the cancellation falls in the late band and the fee is the estimated minimum charge multiplied by the late-cancel percentage of 0.50 (fifty percent), rounded half-up to whole cents. If the lead time is negative — the reserved start has already passed — the cancellation falls in the no-show band and the fee is the estimated minimum charge multiplied by the no-show percentage of 0.50, again rounded half-up. The estimated minimum charge here is computed exactly as in Section 3.6: the effective plan's `min_block_units` times its `rate_cents`, plus the onsite travel surcharge once when the modality is `ONSITE`.

### 3.8. Disputes, Reopening, and Reconciliation

After a session has `ENDED`, the owning client may dispute its billing — but only before the session has been swept into an issued invoice. A dispute against a session that is not in `ENDED` state is rejected with `ERR_SESSION_NOT_ENDED` (HTTP 409), and a dispute against a session already pulled into an `ISSUED` invoice is rejected with `ERR_SESSION_ALREADY_INVOICED` (HTTP 409). A successful dispute moves the session to `DISPUTED`.

From `DISPUTED`, a coordinator has two moves. They may **reopen** the session, which clears `ended_at` and returns the session to `ACTIVE` so additional billable time can accrue; a subsequent end re-runs session billing from scratch, so the `ACTIVE → ENDED → DISPUTED → ACTIVE` loop may repeat as a revision cycle. Alternatively, they may **reconcile** the session by supplying `corrected_billed_units`, which must be a whole number of zero or more; a negative or non-integer value is rejected with `ERR_INVALID_CORRECTED_UNITS` (HTTP 400). Reconciliation recomputes `billed_amount_cents` from the corrected units against the effective rate plan — the corrected figure is treated as already-whole units, still floored to the plan's `min_block_units`, with the same rate and the same onsite surcharge rule applied — and moves the session to `RECONCILED`, which is terminal and re-pins the assignment's `billing_status` to `BILLABLE` at the corrected amount. Whether a session reaches the end of its life through `ENDED` or `RECONCILED`, completing it advances the parent request to `FULFILLED`.

### 3.9. Quality: Ratings and Complaints

Once a session exists, the client may rate the interpreter with a `score` and an optional `comment`. The score is an integer from 1 through 5 inclusive; a score outside that band is malformed input. Exactly one rating is permitted per session — a second rating attempt on the same session is rejected with `ERR_ALREADY_RATED` (HTTP 409). At rating time the system copies the interpreter's identity from the session's assignment onto the rating's `interpreter_id`, then recomputes that interpreter's quality figures. The recomputation counts every rating filed for the interpreter regardless of the underlying session's status: `rating_count` becomes the number of those ratings, and `rating_avg` becomes the sum of their scores divided by that count, rounded half-up to one decimal place. Before the first rating lands `rating_avg` is null; the moment the first rating arrives, `rating_avg` becomes exactly that score and the selection logic of Section 3.3 switches from the 4.0 default to the interpreter's real average. Ratings can be listed per session and listed platform-wide filtered by `interpreter_id` or by `session_id`.

Complaints follow a longer, looping path. A client files a complaint naming the `session_id` and a `category` of `QUALITY`, `CONDUCT`, `BILLING`, or `NO_SHOW`; the complaint opens in `FILED` status, and the system copies the owning `client_id` from the session's request, while `remedy_credit_cents` begins at 0. An administrator moves a filed complaint to `UNDER_REVIEW`. From review, the administrator may request more information, moving the complaint to `NEEDS_INFO`; the owning client then resubmits, moving it back to `UNDER_REVIEW`. This review-and-revert loop between `UNDER_REVIEW` and `NEEDS_INFO` may repeat any number of times before resolution. From `UNDER_REVIEW`, the administrator resolves the complaint with a `disposition` of either `UPHELD` or `DISMISSED`. A dismissal moves the complaint to `DISMISSED` with no billing effect. An upheld complaint moves it to `UPHELD`; and when the category is `BILLING` or `NO_SHOW`, upholding cascades a refund — the session's assignment has its `billing_status` set to `WAIVED`, the complaint's `remedy_credit_cents` is set to the session's `billed_amount_cents`, and if that session had already been swept into an `ISSUED` invoice, the same amount is debited from the client's `outstanding_balance_cents`. An upheld `QUALITY` or `CONDUCT` complaint carries no billing cascade.

### 3.10. Invoicing and Settlement

A coordinator opens an invoice for a `client_id`, which begins as a `DRAFT` and immediately sweeps that client's billable, not-yet-invoiced work into itself: every assignment whose `billing_status` is `BILLABLE`, together with the cancellation and no-show fees recorded on the associated requests. The sweep computes the invoice's `line_count` (the number of billable sessions gathered), `subtotal_cents` (the sum of the swept sessions' `billed_amount_cents`), `fees_cents` (the sum of the swept cancellation and no-show fees), and `total_cents` (the subtotal plus the fees), and it flips each swept assignment's `billing_status` to `INVOICED`. If there is nothing billable and no pending fees for the client, the open is rejected with `ERR_NOTHING_TO_INVOICE` (HTTP 409).

A draft invoice is then issued, which pins `total_cents` and adds it to the client's `outstanding_balance_cents`. Issuing is the second fiscal checkpoint: if adding the total would carry the client over its `credit_limit_cents`, the issue is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`. Issuing an invoice that is not in `DRAFT` is rejected with `ERR_INVOICE_NOT_DRAFT` (HTTP 409). Finally, a coordinator settles an issued invoice, moving it to `SETTLED` and subtracting its `total_cents` from the client's `outstanding_balance_cents`; settling an invoice that is not in `ISSUED` state is rejected with `ERR_INVOICE_NOT_ISSUED` (HTTP 409). An invoice's `status` therefore runs `DRAFT`, `ISSUED`, `SETTLED`, with `VOID` reserved for invalidated drafts. Invoices can be fetched and listed, filterable by client and by status.

### 3.11. Encounter Reporting

After a session has ended, the client may file an **encounter report** documenting it. The report carries a `subject_ref` — an opaque client-side reference such as a case number or record placeholder that is never used in any business decision — and a free-text `summary`; the system stamps `filed_at` with the current clock. Encounter reports are purely documentary and can be listed back per session.

## 4. Endpoint Definitions

Creation endpoints that mint a brand-new resource return HTTP 201; endpoints that modify, transition, or act on an existing resource return HTTP 200. The clock-control endpoint returns 200. Request and response bodies are not restated here — reconstruct each operation's inputs, side effects, and outputs from the Section 3 narratives.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/interpretation/clients` | Create a client (hospital/court) account | PlatformAdmin |
| GET | `/interpretation/clients/{id}` | Fetch a client account including computed outstanding balance | PlatformAdmin, ClientAccount, CoordinatorOps |
| POST | `/interpretation/clients/{id}/suspend` | Suspend a client account | PlatformAdmin |
| POST | `/interpretation/rate-plans` | Create/replace the active rate row for a (client, tier, modality) key | PlatformAdmin |
| GET | `/interpretation/rate-plans/{id}` | Fetch a single rate plan row | PlatformAdmin, CoordinatorOps |
| GET | `/interpretation/rate-plans` | List rate plan rows, filterable by client | PlatformAdmin, CoordinatorOps |
| POST | `/interpretation/language-pairs` | Register a language pair | PlatformAdmin |
| GET | `/interpretation/language-pairs/{id}` | Fetch a language pair | PlatformAdmin, CoordinatorOps, Interpreter |
| POST | `/interpretation/interpreters` | Onboard an interpreter into the pool | PlatformAdmin |
| GET | `/interpretation/interpreters/{id}` | Fetch an interpreter including computed rating/load fields | PlatformAdmin, CoordinatorOps, Interpreter |
| GET | `/interpretation/interpreters` | List interpreters in the pool | PlatformAdmin, CoordinatorOps |
| POST | `/interpretation/interpreters/{id}/status` | Set an interpreter's availability | PlatformAdmin, Interpreter |
| POST | `/interpretation/interpreters/{id}/certifications` | Attach a certification to an interpreter | PlatformAdmin |
| GET | `/interpretation/interpreters/{id}/certifications` | List an interpreter's certifications | PlatformAdmin, CoordinatorOps, Interpreter |
| POST | `/interpretation/certifications/{id}/revoke` | Administratively revoke a certification | PlatformAdmin |
| POST | `/interpretation/interpreters/{id}/languages` | Grant an interpreter a serviceable language pair | PlatformAdmin |
| GET | `/interpretation/interpreters/{id}/languages` | List an interpreter's language grants | PlatformAdmin, CoordinatorOps |
| GET | `/interpretation/interpreter-languages/{id}` | Fetch a single language-grant junction | PlatformAdmin, CoordinatorOps |
| GET | `/interpretation/interpreter-languages` | List language-grant junctions, filterable by language pair / interpreter | PlatformAdmin, CoordinatorOps |
| POST | `/interpretation/requests` | File an interpretation request (on-demand or scheduled) | ClientAccount |
| GET | `/interpretation/requests/{id}` | Fetch a request | PlatformAdmin, CoordinatorOps, ClientAccount |
| GET | `/interpretation/requests` | List requests, filterable by client/language pair/status | PlatformAdmin, CoordinatorOps, ClientAccount |
| POST | `/interpretation/requests/{id}/dispatch` | Dispatch a request: select interpreter, create assignment (OCC-guarded) | CoordinatorOps |
| POST | `/interpretation/requests/{id}/cancel` | Cancel a request; may incur a cancellation fee | ClientAccount |
| GET | `/interpretation/assignments/{id}` | Fetch an assignment (both status dimensions) | PlatformAdmin, CoordinatorOps, Interpreter |
| GET | `/interpretation/assignments` | List assignments, filterable by request/interpreter/lifecycle | PlatformAdmin, CoordinatorOps, Interpreter |
| POST | `/interpretation/assignments/{id}/accept` | Accept an offered assignment | Interpreter |
| POST | `/interpretation/assignments/{id}/decline` | Decline an offered assignment | Interpreter |
| POST | `/interpretation/assignments/{id}/start-session` | Start the session for an accepted assignment | Interpreter |
| GET | `/interpretation/sessions/{id}` | Fetch a session including computed billing fields | PlatformAdmin, CoordinatorOps, Interpreter, ClientAccount |
| GET | `/interpretation/sessions` | List sessions, filterable by assignment/status | PlatformAdmin, CoordinatorOps, Interpreter, ClientAccount |
| POST | `/interpretation/sessions/{id}/connect` | Connect; session becomes ACTIVE | Interpreter |
| POST | `/interpretation/sessions/{id}/end` | End the session; run billing | Interpreter |
| POST | `/interpretation/sessions/{id}/mark-no-show` | Record a no-show for client or interpreter | CoordinatorOps |
| POST | `/interpretation/sessions/{id}/dispute` | Dispute an ended session's billing | ClientAccount |
| POST | `/interpretation/sessions/{id}/reopen` | Reopen a disputed session to ACTIVE | CoordinatorOps |
| POST | `/interpretation/sessions/{id}/reconcile` | Reconcile a disputed session with corrected units | CoordinatorOps |
| POST | `/interpretation/sessions/{id}/rating` | Rate a session (one per session) | ClientAccount |
| GET | `/interpretation/sessions/{id}/ratings` | List ratings for a session | PlatformAdmin, CoordinatorOps, ClientAccount |
| GET | `/interpretation/ratings/{id}` | Fetch a single rating | PlatformAdmin, CoordinatorOps |
| GET | `/interpretation/ratings` | List ratings, filterable by interpreter/session | PlatformAdmin, CoordinatorOps |
| POST | `/interpretation/sessions/{id}/encounters` | File an encounter report after a session ends | ClientAccount |
| GET | `/interpretation/sessions/{id}/encounters` | List encounter reports for a session | PlatformAdmin, CoordinatorOps, ClientAccount |
| POST | `/interpretation/complaints` | File a complaint about a session | ClientAccount |
| GET | `/interpretation/complaints/{id}` | Fetch a complaint | PlatformAdmin, CoordinatorOps, ClientAccount |
| GET | `/interpretation/complaints` | List complaints, filterable by client/session/status | PlatformAdmin, CoordinatorOps, ClientAccount |
| POST | `/interpretation/complaints/{id}/review` | Move a complaint into review | PlatformAdmin |
| POST | `/interpretation/complaints/{id}/request-info` | Request more info from the client | PlatformAdmin |
| POST | `/interpretation/complaints/{id}/resubmit` | Resubmit a complaint needing info | ClientAccount |
| POST | `/interpretation/complaints/{id}/resolve` | Resolve a complaint UPHELD or DISMISSED | PlatformAdmin |
| POST | `/interpretation/invoices` | Open a draft invoice and sweep billable work | CoordinatorOps |
| GET | `/interpretation/invoices/{id}` | Fetch an invoice | PlatformAdmin, CoordinatorOps, ClientAccount |
| GET | `/interpretation/invoices` | List invoices, filterable by client/status | PlatformAdmin, CoordinatorOps, ClientAccount |
| POST | `/interpretation/invoices/{id}/issue` | Issue a draft invoice; pin total, raise outstanding balance | CoordinatorOps |
| POST | `/interpretation/invoices/{id}/settle` | Settle an issued invoice; lower outstanding balance | CoordinatorOps |
| POST | `/interpretation/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_NO_QUALIFIED_INTERPRETER` | 409 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_INTERPRETER_DOUBLE_BOOKED` | 409 |
| `ERR_CLIENT_WINDOW_CONFLICT` | 409 |
| `ERR_INTERPRETER_AT_CAPACITY` | 409 |
| `ERR_ALREADY_RATED` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_STALE_REQUEST_VERSION` | 412 |
| `ERR_CLIENT_SUSPENDED` | 403 |
| `ERR_INVALID_WINDOW` | 400 |
| `ERR_SESSION_NOT_ENDED` | 409 |
| `ERR_NO_RATE_PLAN` | 409 |
| `ERR_INVALID_NO_SHOW_PARTY` | 400 |
| `ERR_INVALID_CORRECTED_UNITS` | 400 |
| `ERR_SESSION_ALREADY_INVOICED` | 409 |
| `ERR_INVOICE_NOT_DRAFT` | 409 |
| `ERR_INVOICE_NOT_ISSUED` | 409 |
| `ERR_NOTHING_TO_INVOICE` | 409 |
| `ERR_INTERPRETER_DEACTIVATED` | 409 |
