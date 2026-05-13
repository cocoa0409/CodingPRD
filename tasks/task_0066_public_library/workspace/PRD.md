# Public Library API — Product Requirements Document

## 1. Introduction

A modern public-library operation spans many small but tightly coupled processes: cataloging bibliographic records to the MARC standard, tracking each physical copy's location and condition, registering readers and issuing borrowing cards, executing the circulation desk (borrow, renew, recall, return), running a fair reservation queue, accruing and settling overdue fines, coordinating inter-library loans with partner libraries, and feeding back acquisition suggestions submitted by readers. The shared challenge across these processes is consistency — a copy that is dispatched to a partner library cannot simultaneously be loaned to a walk-in patron, a fine that was already paid cannot be paid a second time, and a reservation that became ready must, when the holder appears, fast-track into a loan even though the underlying copy never visibly returned to general circulation.

This document specifies the HTTP API of a back-end service that coordinates all of these workflows. The service is consumed by self-service kiosks, counter terminals operated by library staff, an online reader portal, and inter-library messaging glue. It must guarantee a single source of truth for every copy's whereabouts, every loan's due date, every fine's outstanding amount, and every reader's overall borrowing posture. All endpoints are mounted under the `/library` URL prefix. The service is the system-of-record for circulation; external systems (payment provider, national identity-verification platform, partner-library platform) are integrated through inbound events rather than synchronous calls.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two authentication headers:

- `X-User-ID` — identifier of the calling principal.
- `X-User-Role` — one of `Reader`, `Librarian`, `FineOfficer`, `ILLCoordinator`, or `Admin`. The spelling is exact and case-sensitive.

If either header is missing, the request is rejected with `ERR_AUTH_REQUIRED` (HTTP 401). If both headers are present but the role is not authorized for the requested endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The five roles partition responsibilities as follows:

- **`Reader`** is a library patron acting through one of their own cards. The `Reader` role is **entity-backed**: when `X-User-Role` is `Reader`, the `X-User-ID` is the `id` of the acting `Reader` row. Ownership checks on any resource that references a reader (a `Card`, `Loan`, `Reservation`, `Fine`, `ILLRequest`, or `AcquisitionSuggestion`) compare the resource's `reader_id` (or, for cards, the resource's `id` itself joined to its `reader_id`) to the `X-User-ID`. A `Reader` acting on someone else's resource is rejected with `ERR_FORBIDDEN`.
- **`Librarian`** is library staff who run the circulation desk and catalog. The role is **opaque**: when `X-User-Role` is `Librarian`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it (for example, as the actor on an audit log entry) but does not compare it to any entity's `id`.
- **`FineOfficer`** handles waivers and payment processing. The role is opaque (same semantics as `Librarian`).
- **`ILLCoordinator`** owns the inter-library-loan workflow. The role is opaque.
- **`Admin`** owns blacklist management, the audit log, and the operational test-driving capabilities (clock, sweep, events). The role is opaque.

Every audited operation captures the requesting `actor_role` and `actor_id` on the resulting `AuditLog` entry; for `system`-initiated events (cascade promotion, sweep, automatic recompute) `actor_id` is null.

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

All list endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, has a minimum of 1, and a maximum of 100; requests beyond those bounds are rejected with `ERR_INVALID_INPUT`. The `offset` parameter defaults to 0 and must be a non-negative integer. List endpoints sort results by `created_at` in ascending order. The `meta` envelope on every list response exposes the effective `limit`, the effective `offset`, the `total_count` of records that satisfy the filters, and the `has_more` boolean derived from `offset + limit < total_count`.

### 2.4. Common Resource Properties

Every persisted resource carries a server-minted `id`, a string holding a UUID with no type prefix. The `created_at` timestamp is set when the resource is first persisted; it is an ISO 8601 UTC string with three fractional digits and never changes. Resources whose lifecycle includes mutation also carry an `updated_at` timestamp (same format as `created_at`, advanced on every state change or field write) and an integer `version` counter that begins at 1 and increments by 1 on every persisted mutation. All entities defined in this document carry the full set (`id`, `created_at`, `updated_at`, `version`) **except** `AuditLog`, which is append-only — `AuditLog` rows carry only `id` and `created_at`; they have no `updated_at` and no `version`.

### 2.5. Optimistic Concurrency Control

Endpoints that mutate an existing resource (renew, recall, return, freeze, unfreeze, reissue, blacklist, unblacklist, waive, pay, weed, ILL approve/reject/dispatch/return-received, reservation cancel, suggestion start-review and decide) accept an optional `version` field in the request body. When the client supplies `version` and the value does not equal the resource's current `version`, the request is rejected with `ERR_VERSION_CONFLICT` (HTTP 409). Omitting the `version` field skips the check and accepts whatever the latest persisted state is.

### 2.6. Nested-Resource Path Resolution

Endpoint paths are validated left-to-right. For an URL like `/library/book-titles/{id}/copies`, the title `id` is resolved first; if the title does not exist the response is `ERR_NOT_FOUND` (HTTP 404). The same rule extends to deeper nestings — every path segment that names a resource must resolve, and the first unresolved segment determines the error. Foreign keys referenced in request bodies (`copy_id`, `card_id`, `reservation_id`, `book_title_id`) are validated the same way: an unresolvable id surfaces as `ERR_NOT_FOUND`.

### 2.7. Hierarchical Consistency and Cascading Side Effects

Many state transitions in this system cascade into sibling or parent entities. When a `Loan` returns, the underlying `Copy` flips out of `ON_LOAN`; when that flip happens and a reservation queue head exists for the same title, the `Copy` is promoted into `RESERVED` (instead of `AVAILABLE`) and the head `Reservation` moves to `READY_FOR_PICKUP`. When all copies of a `BookTitle` have been weeded, the title itself transitions from `ACTIVE` to `WITHDRAWN`. Every entity touched by a cascade has its own `updated_at` refreshed and its `version` incremented, so a reader who observed `Reservation.version = 3` and `Copy.version = 7` before a return event will observe both values incremented after the return has been processed. The `BookTitle.total_copies` and `BookTitle.available_copies` counters are recomputed by re-aggregating live `Copy` rows on every transition that affects them; the counters are never permitted to drift from their canonical aggregation.

### 2.8. Audit Logging

Mutations that alter the circulation or fiscal posture of a reader produce an `AuditLog` entry. Each entry records the `event_type`, the `subject_type` of the entity it concerns (the entity name as a string, for example `Loan`, `Fine`, or `Reservation`), the `subject_id` of that entity, the `actor_role` and `actor_id` of the principal who triggered the change, a `payload` JSON object snapshotting the relevant before/after fields, and the `occurred_at` timestamp at which the event was recorded. The `event_type` values are exactly `LOAN_CREATED`, `LOAN_RENEWED`, `LOAN_RECALLED`, `LOAN_RETURNED`, `FINE_ACCRUED`, `FINE_WAIVED`, `FINE_PAID`, `RESERVATION_CREATED`, and `RESERVATION_FULFILLED`. Cascade-driven events use `actor_role = "System"` with a null `actor_id`.

### 2.9. Validation Order

When several validation rules might reject a single request, the server evaluates them in a fixed order so that the returned `error_id` is deterministic. Authentication is checked first (missing headers, then disallowed role, then reader-on-someone-else's-resource). Existence checks come next: path resources first, then body-referenced foreign keys. Concurrency-control (`version`) is then validated. Only after those system-level guards pass does the server evaluate state-machine eligibility (is the transition declared from the resource's current state at all), then resource-specific state preconditions (the copy is in the right state for the operation, the card is `ACTIVE`, the reader is identity-verified for card issuance), then reader-posture safety (`BLACKLISTED` rejects unconditionally), then fiscal posture (`unpaid_fine_cents` must be zero for new loans and renewals), then business-quantity constraints (quota, renewal limits, active-reservation-blocks-renewal, recall flag), then temporal constraints (reservation hold not yet expired, ILL loan period elapsed), and finally fine-arithmetic and input-shape checks. Because the order is fixed, a request that would simultaneously fail authentication and fail a quota check always returns the authentication error, never the quota error.

### 2.10. Fiscal Precision and Money Representation

All monetary amounts (fine accrual, payments, waivers, ILL settlement) are represented in integer cents. Day counts derived from time deltas (overdue days, ILL loan-period elapsed) use ceiling rounding: any fraction of a day counts as a full day. Where rounding is required inside the ILL settlement computation, the rounding method is half-up (an amount of `0.5` cents rounds up to `1`). The ordering of rounding versus aggregation matters and is specified precisely in §3.

### 2.11. Concurrency and Race Resolution

Concurrent attempts to mutate the same resource resolve by first-writer-wins on a single critical field for each scenario; the loser is rejected with a specific `error_id` so that clients can distinguish kinds of conflict.

- **Two readers attempt to borrow the same copy after a reservation hold has expired.** At most one `Loan` is created on that copy. The serialization point is the transition of `Copy.status` into `ON_LOAN`; the loser receives `ERR_COPY_NOT_AVAILABLE` (HTTP 409).
- **A renew and a recall are issued concurrently on the same loan.** Exactly one operation succeeds. The serialization point is the write of `Loan.is_recalled`. If recall wins, the renew attempt is rejected with `ERR_LOAN_RECALLED` (HTTP 409).
- **Two reservations are submitted at exactly the same instant for the same title.** Both reservations are accepted; their `queue_position` is assigned by strict ordering on `created_at` ascending, with ties broken by `Reservation.id` in lexicographic ascending order. If a true `version` collision occurs while assigning queue position the loser receives `ERR_VERSION_CONFLICT` (HTTP 409).
- **A pay and a waive are applied concurrently on the same fine and together would over-settle it.** Each operation re-reads `Fine.outstanding_cents` at commit; the second operation, whose requested amount now exceeds the current outstanding, is rejected with `ERR_FINE_OVERPAYMENT` (HTTP 409).
- **A card freeze is applied while a loan request that uses that card is still in flight.** The loan creation re-reads `Card.status` at commit and, if the card is no longer `ACTIVE`, is rejected with `ERR_CARD_NOT_ACTIVE` (HTTP 409).

### 2.12. Operational Test-Driving Capabilities

Because many transitions in this system are gated by wall-clock time (overdue, hold-expiry, card-validity end, ILL loan period), the service exposes three `Admin`-only test-driving capabilities. The clock-advance capability accepts an `iso_duration` field and advances the simulated `now()` that the server uses for all time-gated logic; all subsequent reads of `fine_accrual_provisional`, all subsequent expiry sweeps, and all subsequent `hold_expires_at` and `valid_until` checks observe the new clock. The sweep capability runs a single pass of the periodic operational job: it expires reservations whose `hold_expires_at` is at or before the simulated `now()` (promoting the next `QUEUED` reservation in cascade), expires `Card` rows whose `valid_until` is at or before the simulated `now()`, and recomputes `Reader.status` for every reader. The event-emit capability ingests inbound events from external systems and is described in §3 alongside the workflows it drives.

## 3. Business Logic & Workflows

### 3.1. Bibliographic Cataloging and Physical Copies

The cataloging workflow starts when a `Librarian` enters a new bibliographic record. The payload carries the MARC `marc_control_number` (between 8 and 20 characters long and globally unique across `BookTitle`), the `isbn` (exactly 13 digits), the bibliographic `title` (MARC 245$a), the primary `author` (MARC 100$a), the `publisher` (MARC 260$b), the `publication_year` (an integer that must be at least 1450 and at most the current calendar year, inclusive on both ends), the `classification_scheme` (either `DEWEY` or `CLC`), the `classification_code` (a subject code such as `813.54` or `I712.45`), the `subject_category` (one of `GENERAL`, `REFERENCE`, `CHILDREN`, or `RARE`), and the `acquisition_source` (one of `PURCHASE`, `DONATION`, `EXCHANGE`, or `ILL_PURCHASE`). Violations of any of these constraints — a duplicate `marc_control_number`, an ISBN of the wrong length, an out-of-range `publication_year`, or an enum value outside the declared set — are rejected with `ERR_INVALID_INPUT` (HTTP 422). On creation the title begins life in `ACTIVE` status with both `total_copies` and `available_copies` equal to zero.

A `BookTitle` is meaningless without physical copies. A `Librarian` adds a `Copy` to a title by supplying the `barcode` (globally unique across all copies), a non-empty `location_code` describing the shelf address (for example `A-12-03`), the per-copy `acquisition_source` (which is independent of the title's acquisition source — a `PURCHASE`d title can have a `DONATION`-sourced copy), and an `acquired_at` timestamp marking when the copy entered the collection. A duplicate `barcode` or an empty `location_code` is rejected with `ERR_INVALID_INPUT`. Each new copy starts in `AVAILABLE` status, and the title's `total_copies` and `available_copies` aggregates are recomputed: `total_copies` is the count of all copies of the title regardless of status, and `available_copies` is the count of those copies whose `status` equals `AVAILABLE`.

Copies are weeded — removed from circulation — when a `Librarian` invokes the weeding action on a single copy, supplying a `weeding_reason` of `DAMAGED`, `LOST`, `OBSOLETE`, or `LOW_CIRCULATION`. The operation is only declared from `AVAILABLE`; a copy that is `ON_LOAN`, `RESERVED`, `IN_TRANSIT_ILL`, or already `WEEDED` is rejected with `ERR_INVALID_STATE` for any transition the state machine does not declare, and a copy that is not in the required `AVAILABLE` state for the operation is rejected with `ERR_COPY_NOT_AVAILABLE`. A weed without a `weeding_reason` is rejected with `ERR_INVALID_INPUT`. The successful weed transitions the copy into `WEEDED` (a terminal state for `Copy`), refreshes the title's `total_copies` and `available_copies`, and, when every copy of the title is in `WEEDED`, advances the parent `BookTitle` from `ACTIVE` to `WITHDRAWN`.

### 3.2. Reader Registration, Identity Verification, and Card Lifecycle

A reader is enrolled by a `Librarian` who supplies the reader's `national_id_hash` (a 64-character SHA-256 hex string, unique across `Reader`) and the reader's `full_name`. The reader begins life with `identity_verified` set to false, `identity_verified_at` null, `status` set to `NORMAL`, `active_loan_count` zero, and `unpaid_fine_cents` zero. The reader cannot yet borrow because they have no card, and they cannot be issued a card while `identity_verified` is false. Identity verification arrives asynchronously from the external identity-verification platform: an `Admin` posts an inbound event of type `IDENTITY_VERIFIED`, whose `payload` references the reader; on receipt the server sets the reader's `identity_verified` flag to true and records the `identity_verified_at` timestamp.

Once verification has arrived, a `Librarian` issues a `Card` to the reader. The request supplies the `card_type` (one of `REGULAR`, `STUDENT`, `SENIOR`, or `TEMPORARY`), the inclusive `valid_from` timestamp, and the exclusive `valid_until` timestamp; the request must satisfy `valid_from` strictly earlier than `valid_until` or the server returns `ERR_INVALID_INPUT`. If the reader's `identity_verified` is still false the request is rejected with `ERR_IDENTITY_NOT_VERIFIED`. On success the server mints a unique human-readable `card_number` of the form `LIB-YYYY-NNNNNN` and derives three computed parameters from `card_type`: the borrowing quota `max_loans` is `5` for `REGULAR`, `8` for `STUDENT`, `4` for `SENIOR`, and `2` for `TEMPORARY`; the loan period `loan_duration_days` is `30` for `REGULAR`, `60` for `STUDENT`, `45` for `SENIOR`, and `14` for `TEMPORARY`; and the per-loan consecutive-renewal limit `max_renewals` is `2` for `REGULAR`, `3` for `STUDENT`, `2` for `SENIOR`, and `0` for `TEMPORARY`. These three values are pinned at issuance and do not change if the card's `card_type` definition is later edited globally. A card starts in `ACTIVE` status with `replaced_by_card_id` null.

A `Librarian` may freeze an `ACTIVE` card; the card moves to `FROZEN` and the reader's overall `status` is recomputed (no change occurs unless the frozen card was the reader's sole active card). Freezing a card that is not in `ACTIVE` is rejected with `ERR_INVALID_STATE`. Unfreezing returns a `FROZEN` card to `ACTIVE`. A card may also be reissued: when a `Librarian` invokes reissue on an `ACTIVE` or `FROZEN` card and supplies the successor card's `card_type`, `valid_from`, and `valid_until` in the request body, the server mints a new `Card` and writes the old card's `replaced_by_card_id` to point at the new card's `id`; the old card transitions to the terminal `REISSUED` state. Existing loans on the old card retain their original `card_id` and original due dates; the `Reader` identity is unchanged, so a loan opened on the predecessor card still references the same `reader_id`. A reissue invoked from any state other than `ACTIVE` or `FROZEN` is rejected with `ERR_INVALID_STATE`. Cards whose `valid_until` is at or before the simulated `now()` are swept to the terminal `EXPIRED` state by the sweep capability; expiry does not disturb any loans that are still open on that card.

`Admin`s manage two posture transitions on the reader itself. Blacklisting a reader (a request that supplies a free-text `reason`) advances `Reader.status` to `BLACKLISTED` and, as a side effect, transitions every `ACTIVE` card of that reader to `FROZEN`. Unblacklisting a reader is only permitted when the reader's `unpaid_fine_cents` is zero and no loan in `BORROWED`, `RENEWED`, or `RECALL_PENDING` is currently overdue; the unblacklist then triggers a status recompute that yields either `NORMAL` or `OVERDUE`.

### 3.3. Borrowing at the Counter and at the Kiosk

When a patron presents a copy and a card at the counter, or self-scans them at a kiosk, the loan-creation flow begins. The request supplies the `copy_id` of the physical item, the `card_id` of the acting card, the `channel` of the loan (`COUNTER` or `KIOSK`), and — when the loan fulfills a pending reservation — the `reservation_id` of that reservation. The server walks its safety gates before persisting: the path and body references must resolve (otherwise `ERR_NOT_FOUND`), the copy must be in the state required by the operation (otherwise `ERR_COPY_NOT_AVAILABLE`), the card must be `ACTIVE` (otherwise `ERR_CARD_NOT_ACTIVE`), the reader must not be `BLACKLISTED` (otherwise `ERR_READER_BLACKLISTED`), the reader's `unpaid_fine_cents` must equal zero (otherwise `ERR_UNPAID_FINE`), and the strict borrowing quota must be greater than zero (otherwise `ERR_QUOTA_EXCEEDED`). When the request includes a `reservation_id` the reservation must currently be in `READY_FOR_PICKUP` with `hold_expires_at` strictly later than the simulated `now()`; if the hold deadline has already been reached the operation is rejected with `ERR_HOLD_EXPIRED`. The acting card's `reader_id` must match the reservation's `reader_id`, otherwise the request fails the standard ownership check with `ERR_FORBIDDEN`.

On success the server creates a `Loan` whose `copy_id` and `card_id` are taken from the request, whose `reader_id` is copied from the card's `reader_id` at this moment (and is permanently pinned — a later reissue of the card does not retroactively alter the loan), whose `borrowed_at` is the moment of creation, and whose `due_at` is `borrowed_at` plus the card's `loan_duration_days`. The new loan starts in `BORROWED` with `renewals_used` zero, `is_recalled` false, `recall_due_at` null, and `returned_at` null. The underlying copy transitions from `AVAILABLE` (or from `RESERVED` when a `reservation_id` was supplied) to `ON_LOAN`. The reservation, if any, transitions to the terminal `FULFILLED` state. The title's `total_copies` and `available_copies` are recomputed. The reader's `active_loan_count` and `status` are recomputed. An `AuditLog` entry of `event_type` `LOAN_CREATED` is appended.

The borrowing quota is the result of a calculation that the system exposes for inspection: an inspection endpoint on a card supports a `mode` query parameter to choose between two readings. In **strict** mode (the default and the one used to gate new loan creation) the remaining quota is computed as the card's `max_loans` minus the count of loans on this card whose `status` is one of `BORROWED`, `RENEWED`, or `RECALL_PENDING`, minus the count of reservations on this reader whose `status` is one of `QUEUED` or `READY_FOR_PICKUP`, clamped to a floor of zero. In **chronological** mode — used by reports and audits, never by enforcement — the remaining quota is computed as the card's `max_loans` minus the same count of in-flight loans, without subtracting reservations. The two readings can differ: a card with `max_loans` of `5`, three in-flight loans, and one active reservation reports a strict remaining of `1` and a chronological remaining of `2`. Loan creation gates on the strict mode reading; `borrowing_quota_remaining_strict` must be strictly greater than zero at the moment of commit or the operation is rejected with `ERR_QUOTA_EXCEEDED`.

### 3.4. Renewal, Recall, and Return

A patron renews a loan when they want more time. Renewing is permitted only when the loan is currently in `BORROWED` and the loan's `renewals_used` is strictly less than the card's `max_renewals`. The loan must not have been recalled (`is_recalled` must be false), the reader's overall `status` must be `NORMAL`, the reader's `unpaid_fine_cents` must be zero, and no active reservation may exist for the loan's underlying `BookTitle`. Violations map to errors in the order listed in §2.9: a renew attempted on a non-`BORROWED` loan returns `ERR_INVALID_STATE`; a renew on a card whose `status` is not `ACTIVE` returns `ERR_CARD_NOT_ACTIVE`; a blacklisted reader receives `ERR_READER_BLACKLISTED`; a reader with positive `unpaid_fine_cents` receives `ERR_UNPAID_FINE`; a renew at or beyond the renewal limit returns `ERR_RENEWAL_LIMIT_REACHED`; a renew while an active reservation exists for the title returns `ERR_RESERVATION_BLOCKS_RENEWAL`; a renew on an already-recalled loan returns `ERR_LOAN_RECALLED`. On success the loan transitions through `RENEWED` and conceptually re-enters `BORROWED` so that another renewal cycle (up to `max_renewals`) is possible: `renewals_used` is incremented by one, the new `due_at` is the larger of the current `due_at` and the simulated `now()`, advanced by the card's `loan_duration_days`, and an `AuditLog` entry of `event_type` `LOAN_RENEWED` is appended.

A `Librarian` recalls an outstanding loan with a request that supplies a free-text `reason`. Recall is declared from `BORROWED` or `RENEWED` and requires either that an active reservation exists for the loan's underlying title or that the loan is overdue (the simulated `now()` is strictly later than the loan's `due_at`). On success the loan transitions to `RECALL_PENDING`, `is_recalled` is set to true, and `recall_due_at` is set to the smaller of (a) the existing `due_at` and (b) the simulated `now()` plus the recall grace period of three days. The reader's posture is recomputed, and an `AuditLog` entry of `event_type` `LOAN_RECALLED` is appended.

When a patron returns a loan, the request may include an explicit `returned_at` timestamp (used by counter operators reconciling a back-dated drop-off) and a `version`; if `returned_at` is omitted the simulated `now()` is used. The effective due date for the return is `recall_due_at` if `is_recalled` is true, and `due_at` otherwise. If `returned_at` is at or before the effective due date the loan transitions to the terminal `RETURNED` state and no fine is generated. If `returned_at` is strictly later than the effective due date the loan transitions to the terminal `OVERDUE_CLOSED` state and a `Fine` is finalized as described in §3.6. In either outcome the underlying copy is released: it normally returns to `AVAILABLE`, but when a reservation in `QUEUED` exists for the same title the copy is promoted directly to `RESERVED` and the queue-head reservation moves to `READY_FOR_PICKUP` with a fresh `hold_expires_at` set to the simulated `now()` plus the hold period (48 hours, expressed below as a window of two days). The title's `available_copies` is incremented (or replaced by the reservation cascade), the reader's `active_loan_count` and `status` are recomputed, and an `AuditLog` entry of `event_type` `LOAN_RETURNED` is appended.

### 3.5. Reservations and the Hold Window

A reservation is filed against a `BookTitle` rather than a specific copy — the queue absorbs whichever copy of that title next becomes available. The request supplies the `book_title_id`, the acting `card_id`, and the `channel` (`ONLINE` or `ON_SITE`). The acting card must be `ACTIVE`, otherwise the request is rejected with `ERR_CARD_NOT_ACTIVE`. The same reader may not hold two open positions for the same title at once: if the reader already has a `Reservation` for that title in `QUEUED` or `READY_FOR_PICKUP`, or a `Loan` for any copy of that title in `BORROWED`, `RENEWED`, or `RECALL_PENDING`, the request is rejected with `ERR_DUPLICATE_RESERVATION`. The new reservation's `reader_id` is copied from the acting card at creation time. Its `queue_position` is assigned by taking the existing `QUEUED` reservations on the same title, sorting them ascending by `created_at` and then by `id` to break ties, and assigning the new reservation a 1-indexed position one past the last existing position. The reservation enters `QUEUED` with `held_copy_id` null and `hold_expires_at` null.

When a copy of the title is available at the moment of submission and this new reservation lands at the head of the queue, the cascade fires immediately: the head reservation jumps from `QUEUED` to `READY_FOR_PICKUP` with `held_copy_id` set to that copy's `id` and `hold_expires_at` set to the simulated `now()` plus the hold period of two days; the copy itself transitions from `AVAILABLE` to `RESERVED`. The same `QUEUED → READY_FOR_PICKUP` cascade also fires when a loan is returned and a queue head was waiting (§3.4), and when a `READY_FOR_PICKUP` reservation expires and the next `QUEUED` head is promoted in its place — a depth-two cascade where the expiry of one reservation directly triggers promotion of the next.

A `READY_FOR_PICKUP` reservation must be picked up before `hold_expires_at` is reached: when a loan is created with a `reservation_id` and the simulated `now()` is at or after `hold_expires_at`, the request is rejected with `ERR_HOLD_EXPIRED`. The operational sweep is responsible for expiring stale holds: any reservation whose `hold_expires_at` is at or before the simulated `now()` is moved to the terminal `EXPIRED` state, and the underlying copy is released — if another `QUEUED` reservation exists for the same title it is promoted and the copy remains `RESERVED`, otherwise the copy returns to `AVAILABLE`.

A reader may cancel their own reservation. Cancellation is permitted from `QUEUED` and from `READY_FOR_PICKUP`. Cancellation of a `QUEUED` reservation moves it to the terminal `CANCELLED` state and shifts the `queue_position` of every trailing `QUEUED` reservation down by one. Cancellation of a `READY_FOR_PICKUP` reservation moves it to `CANCELLED` and releases the held copy back into circulation, promoting the next `QUEUED` head (if any) and otherwise returning the copy to `AVAILABLE`.

### 3.6. Overdue Fines: Accrual, Display, Waiver, and Payment

Fines are accrued by category. The daily-rate-by-`subject_category` schedule is fixed at issuance time of the fine: the per-day rate `daily_rate_cents` is `20` for `GENERAL`, `50` for `REFERENCE`, `10` for `CHILDREN`, and `200` for `RARE`. The per-copy fine cap `fine_cap_cents` is `5000` for `GENERAL`, `10000` for `REFERENCE`, `2000` for `CHILDREN`, and `50000` for `RARE`. A `Fine` exists at most once per `Loan` and is created lazily — only when a return happens late and the final accrual is strictly positive. The fine carries `loan_id` and `reader_id` copied from the parent loan, and `subject_category` copied from the parent `BookTitle` at the moment of creation.

The fine arithmetic has two distinct readings of the same shape, distinguished only by what stands in for the return moment:

- **Provisional reading** — exposed via the loan-fetch endpoint while the loan is still in `BORROWED`, `RENEWED`, or `RECALL_PENDING`. The effective due date is `recall_due_at` if `is_recalled` is true, otherwise `due_at`. If the simulated `now()` is at or before the effective due date the provisional value is zero. Otherwise the number of overdue days is the difference between the simulated `now()` and the effective due date, expressed as a positive duration in days and rounded up to the next whole day; the raw provisional amount is that day count multiplied by `daily_rate_cents`, and the reported provisional value is the smaller of that raw amount and `fine_cap_cents`. The provisional value is computed live on each read; the same loan read at different moments returns different provisional values. It is never persisted.
- **Final reading** — computed exactly once at the moment of return when the loan transitions to `OVERDUE_CLOSED`. The effective due date is the same recall-aware value, but the moment used is `returned_at` (a fixed timestamp), not the simulated `now()`. The number of overdue days is the difference between `returned_at` and the effective due date, expressed in days and rounded up. If that day count is zero or negative no `Fine` is created. Otherwise the raw final amount is the day count multiplied by `daily_rate_cents`, and `Fine.accrued_cents` is set to the smaller of that raw amount and `fine_cap_cents`. This value is permanent.

A worked example illuminates the divergence: an identical loan whose effective due date is fixed and which is first inspected three days past due and then returned five days past due will report a provisional value of three days' worth of fine on the inspection read, but its permanent `accrued_cents` records five days' worth — provisional uses live `now()`, final uses `returned_at`.

When a `Fine` is created its `waived_cents` and `paid_cents` are zero, its `outstanding_cents` is equal to `accrued_cents` minus `waived_cents` minus `paid_cents` (so initially equal to `accrued_cents`), and its `settlement_status` is `PENDING`. A `FineOfficer` may waive part or all of the fine in a single request: the request supplies `waive_cents` and a `reason` of `SYSTEM_FAULT`, `HOLIDAY`, or `HARDSHIP`. The waive is rejected with `ERR_INVALID_WAIVER` (HTTP 422) when the reason is outside that set or when the requested `waive_cents` is larger than the current `outstanding_cents`; it is rejected with `ERR_FINE_OVERPAYMENT` (HTTP 409) when a concurrent operation has already reduced the outstanding below the requested amount at commit time. On a successful waive the fine's `waived_cents` is increased by `waive_cents`, `outstanding_cents` is recomputed, and an `AuditLog` entry of `event_type` `FINE_WAIVED` is appended with a before/after snapshot in its `payload`. A waiver may be repeated until cumulative waivers and payments cover the accrued amount — the transition out of `PENDING` is described below.

Payment of a fine is two-step. First, an external payment provider posts a `PAYMENT_CONFIRMED` event to the event-emit endpoint; the event's `payload` carries an `idempotency_key` that uniquely identifies the payment intent. Second, the `Reader` (or a `FineOfficer` on their behalf) calls the fine-pay endpoint with `pay_cents`, the matching `idempotency_key`, and an optional `version`. If no matching `PAYMENT_CONFIRMED` event has been recorded for that `idempotency_key`, the payment is rejected with `ERR_PAYMENT_EVENT_MISSING`. If the requested `pay_cents` exceeds the current `outstanding_cents`, the payment is rejected with `ERR_FINE_OVERPAYMENT`. On success the fine's `paid_cents` is increased by `pay_cents`, `outstanding_cents` is recomputed, and an `AuditLog` entry of `event_type` `FINE_PAID` is appended. Whenever a waive or a pay reduces `outstanding_cents` to zero — equivalently, when `accrued_cents` equals `waived_cents` plus `paid_cents` — the fine automatically transitions to the terminal `SETTLED` state, the reader's `unpaid_fine_cents` is recomputed (it is the sum of `outstanding_cents` over the reader's `Fine` rows whose `settlement_status` is `PENDING`), and the reader's overall `status` is recomputed.

The reader's overall posture is the result of a small derivation. A `BLACKLISTED` reader stays `BLACKLISTED` until an `Admin` unblacklists them. Otherwise the server checks whether any loan of the reader in `BORROWED`, `RENEWED`, or `RECALL_PENDING` has its effective due date strictly earlier than the simulated `now()`, and whether any `PENDING` fine of the reader has `outstanding_cents` strictly greater than zero. If either is true the reader's `status` is `OVERDUE`; otherwise it is `NORMAL`. The recompute fires after every loan transition, every fine transition, and every sweep run.

### 3.7. Inter-Library Loan

An inter-library loan is initiated when a patron or staff member files an `ILLRequest` for a title that the library does not hold. The request supplies the acting `card_id`, the `partner_library_code` from the approved partner network (currently `PL_A`, `PL_B`, or `PL_C`; any other value is rejected with `ERR_UNKNOWN_PARTNER`), the `target_marc_control_number` of the item being requested, and the quoted `shipping_cost_cents` per leg (which must be non-negative). The request's `reader_id` is derived from the acting card. The request enters `SUBMITTED` with `handling_fee_cents` initialized to the constant 300 cents per leg, `settlement_total_cents` zero, and the in-transit endpoints null.

The partner library responds asynchronously: an `Admin` posts an inbound event of type `ILL_AVAILABILITY` whose `payload` carries an `available` boolean and (when available) a `partner_max_days` integer. An `ILLCoordinator` then approves the request, which is only permitted while it is `SUBMITTED` and the availability event reported `available = true`. On approval the negotiated `agreed_loan_days` is set to the smaller of the event's `partner_max_days` and the requester's maximum loan period of twenty-one days. Alternatively the coordinator may reject the request (transition `SUBMITTED → REJECTED`); a reject request carries a free-text `reason`.

Once approved, the coordinator dispatches a local copy: the dispatch request supplies a `copy_id` of a copy whose underlying `BookTitle` carries the same `marc_control_number` as the request's `target_marc_control_number` and whose `status` is `AVAILABLE`. The copy transitions from `AVAILABLE` to `IN_TRANSIT_ILL`, the request transitions from `APPROVED` to `IN_TRANSIT`, and `in_transit_from` is set to the moment of dispatch. The partner library then signals delivery (an inbound event of type `ILL_DELIVERED` advances the request from `IN_TRANSIT` to `AT_PARTNER`) and, when ready, initiates the return (an inbound event of type `ILL_RETURN_INITIATED` advances the request from `AT_PARTNER` to `RETURNED_TRANSIT`). The return-initiation event is gated by the negotiated loan period: the simulated `now()` must be at least `in_transit_from` plus `agreed_loan_days` days, where the start of that window is inclusive (the at-or-after instant counts) and the end is exclusive; an attempt before the window opens is rejected with `ERR_ILL_LOAN_PERIOD_NOT_MET`.

When the returning copy arrives, the coordinator records the receipt. The copy's `IN_TRANSIT_ILL` reverts to `AVAILABLE` (possibly cascading to `RESERVED` via the standard promotion if a queue head exists), `in_transit_to` is set to the moment of receipt, the request transitions to the terminal `SETTLED` state, and `settlement_total_cents` is computed for the two-leg journey. The computation is order-sensitive — the rounding happens per leg before the two legs are summed, not after. For each leg the server computes the insurance charge as the leg's `shipping_cost_cents` multiplied by an insurance rate of 2.50%, rounded half-up to whole cents; the leg total is the sum of `shipping_cost_cents`, `handling_fee_cents`, and that insurance charge, rounded half-up to whole cents; and `settlement_total_cents` is the sum of the outbound leg total and the inbound leg total. Because the legs are symmetric — both use the same `shipping_cost_cents` and the same 300-cent `handling_fee_cents` — the two leg totals are equal, but the system still rounds each leg independently before summation. A request to receive the return before the loan period has elapsed is rejected with `ERR_ILL_LOAN_PERIOD_NOT_MET`; a request to receive a return whose ILL state is not `RETURNED_TRANSIT` is rejected with `ERR_INVALID_STATE`.

### 3.8. Reader-Submitted Acquisition Suggestions

A reader may suggest that the library acquire a new title. The submission supplies the acting `card_id`, the `suggested_isbn` (exactly 13 digits), the `suggested_title` text, and a free-form `rationale` explaining why the title would be valuable. The suggestion's `reader_id` is derived from the acting card. The suggestion enters `SUBMITTED` with `review_notes` null and `decision_book_title_id` null.

A `Librarian` advances a suggestion through review. Starting review moves the suggestion from `SUBMITTED` to `UNDER_REVIEW`; a deferred suggestion may later re-enter `UNDER_REVIEW` through the same start-review action, forming a deferral cycle. From `UNDER_REVIEW` the librarian decides the suggestion by supplying a `decision` of `ACQUIRE`, `DECLINE`, or `DEFER`, optional `review_notes`, and — only when the decision is `ACQUIRE` — a `new_book_title` block containing the bibliographic fields needed to catalog the resulting title (the `marc_control_number`, an `isbn` that matches the suggestion's `suggested_isbn`, the `classification_scheme`, the `classification_code`, the `subject_category`, and the `acquisition_source`, which is typically `ILL_PURCHASE` when the acquisition was driven by a suggestion). An `ACQUIRE` decision creates the new `BookTitle` from the supplied block (subject to the same input validation as a direct cataloging — duplicate `marc_control_number`, wrong-length ISBN, or out-of-range `publication_year` all return `ERR_INVALID_INPUT`) and writes `decision_book_title_id` to the new title's `id`; the suggestion transitions to the terminal `ACQUIRED` state. A `DECLINE` decision transitions the suggestion to the terminal `DECLINED` state. A `DEFER` decision transitions the suggestion to `DEFERRED`, from which the librarian can re-initiate review later.

The library also tracks how its suggestion pipeline is performing. A statistics read produces an aggregate object covering the count of suggestions in each lifecycle state and the suggestion-to-acquisition conversion ratio over the lifetime of the collection.

### 3.9. Audit-Log Reading, Sweeps, and Inbound Events

The audit-log read endpoint exposes the append-only `AuditLog`. It accepts pagination parameters and optional filters on `event_type` and on `subject_id`. List ordering is by `created_at` ascending as for every other list endpoint. The endpoint is `Admin`-only.

The periodic operational sweep is the system's catch-all for time-gated transitions: it expires reservations whose `hold_expires_at` is at or before the simulated `now()`, expires cards whose `valid_until` is at or before the simulated `now()`, and recomputes every reader's `status`. Expired reservations cascade through the standard reservation-expiry behavior (promote the next `QUEUED` head if one exists, else return the held copy to `AVAILABLE`).

The event-emit endpoint accepts an `event_type` and a `payload`. The set of recognized event types and their effects is:

- `PAYMENT_CONFIRMED` — records a payment-confirmation token so that a subsequent fine-pay request with a matching `idempotency_key` will be accepted.
- `IDENTITY_VERIFIED` — flips the targeted reader's `identity_verified` flag to true and records `identity_verified_at`.
- `ILL_AVAILABILITY` — supplies the availability decision (`available` true or false) and `partner_max_days` for a pending `ILLRequest`; an availability of false bars subsequent approval (the request can only be moved to `APPROVED` if `available = true`).
- `ILL_DELIVERED` — advances an `ILLRequest` from `IN_TRANSIT` to `AT_PARTNER`.
- `ILL_RETURN_INITIATED` — advances an `ILLRequest` from `AT_PARTNER` to `RETURNED_TRANSIT`, subject to the loan-period gate described in §3.7.

## 4. Endpoint Definitions

All API endpoints listed below are mounted under the `/library` prefix. Endpoints that **create** a brand-new persisted resource respond with HTTP 201 Created and return the new resource in the `data` field of the envelope. Endpoints that **modify** an existing resource, or that read state, respond with HTTP 200 OK and return the updated or read resource. Successful operations on the test-driving endpoints (clock, sweep, event-emit) likewise respond with HTTP 200 OK. Error responses follow the catalog in §5; HTTP status codes for individual errors are documented there.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | /library/book-titles | Catalog a new bibliographic record (MARC entry) | Librarian |
| GET | /library/book-titles | List or search bibliographic records (filters: `classification_scheme`, `subject_category`, `search`) | Reader, Librarian, FineOfficer, ILLCoordinator, Admin |
| GET | /library/book-titles/{id} | Get a bibliographic record | Reader, Librarian, FineOfficer, ILLCoordinator, Admin |
| POST | /library/book-titles/{id}/copies | Add a physical copy under a title | Librarian |
| GET | /library/book-titles/{id}/copies | List copies of a title (filter: `status`) | Reader, Librarian, FineOfficer, ILLCoordinator, Admin |
| POST | /library/copies/{id}/weed | Weed (withdraw) a copy | Librarian |
| POST | /library/readers | Register a reader | Librarian |
| GET | /library/readers/{id} | Get a reader | Reader, Librarian, FineOfficer, ILLCoordinator, Admin |
| POST | /library/readers/{id}/cards | Issue a new card to a verified reader | Librarian |
| POST | /library/cards/{id}/freeze | Freeze a card | Librarian |
| POST | /library/cards/{id}/unfreeze | Unfreeze a card | Librarian |
| POST | /library/cards/{id}/reissue | Issue a successor card; replaces this one | Librarian |
| GET | /library/cards/{id}/quota | Inspect borrowing quota in strict (default) or chronological mode | Reader, Librarian |
| POST | /library/readers/{id}/blacklist | Blacklist a reader | Admin |
| POST | /library/readers/{id}/unblacklist | Lift blacklist; reader returns to NORMAL/OVERDUE per recompute | Admin |
| POST | /library/loans | Borrow a copy (counter or kiosk); optionally fulfills a reservation | Reader, Librarian |
| GET | /library/loans/{id} | Get a loan (includes provisional fine) | Reader, Librarian, FineOfficer, Admin |
| POST | /library/loans/{id}/renew | Renew a loan; extends due_at | Reader, Librarian |
| POST | /library/loans/{id}/recall | Recall an outstanding loan | Librarian |
| POST | /library/loans/{id}/return | Return a loan; if late, finalizes a Fine | Reader, Librarian |
| POST | /library/reservations | Create a reservation for a title (online or on-site) | Reader, Librarian |
| GET | /library/reservations/{id} | Get a reservation | Reader, Librarian, Admin |
| DELETE | /library/reservations/{id} | Cancel a reservation | Reader, Librarian |
| GET | /library/fines/{id} | Get a fine (PENDING or SETTLED) | Reader, FineOfficer, Admin |
| POST | /library/fines/{id}/pay | Apply payment to a fine | Reader, FineOfficer |
| POST | /library/fines/{id}/waive | Apply a waiver to a fine | FineOfficer |
| POST | /library/ill-requests | Submit an inter-library loan request | Reader, Librarian, ILLCoordinator |
| POST | /library/ill-requests/{id}/approve | Approve an ILL request after availability event | ILLCoordinator |
| POST | /library/ill-requests/{id}/reject | Reject an ILL request | ILLCoordinator |
| POST | /library/ill-requests/{id}/dispatch | Dispatch a local copy to the partner library | ILLCoordinator |
| POST | /library/ill-requests/{id}/return-received | Receive the returning ILL copy and settle | ILLCoordinator |
| POST | /library/acquisition-suggestions | Submit an acquisition suggestion | Reader |
| POST | /library/acquisition-suggestions/{id}/start-review | Move a suggestion into review | Librarian |
| POST | /library/acquisition-suggestions/{id}/decide | Decide a suggestion (ACQUIRE, DECLINE, DEFER) | Librarian |
| GET | /library/acquisition-suggestions/stats | Suggestion-to-acquisition statistics | Librarian, Admin |
| GET | /library/audit-logs | Read audit-log entries (filters: `event_type`, `subject_id`) | Admin |
| POST | /library/_clock/advance | Advance the simulated clock by a duration | Admin |
| POST | /library/_sweep/run | Run the periodic ops sweep (reservation expiry, card expiry, reader-status recompute) | Admin |
| POST | /library/_events/emit | Emit an inbound external event | Admin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|------------------|
| ERR_AUTH_REQUIRED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_INPUT | 422 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_COPY_NOT_AVAILABLE | 409 |
| ERR_CARD_NOT_ACTIVE | 409 |
| ERR_IDENTITY_NOT_VERIFIED | 409 |
| ERR_READER_BLACKLISTED | 409 |
| ERR_UNPAID_FINE | 409 |
| ERR_QUOTA_EXCEEDED | 409 |
| ERR_RENEWAL_LIMIT_REACHED | 409 |
| ERR_RESERVATION_BLOCKS_RENEWAL | 409 |
| ERR_LOAN_RECALLED | 409 |
| ERR_HOLD_EXPIRED | 409 |
| ERR_INVALID_WAIVER | 422 |
| ERR_FINE_OVERPAYMENT | 409 |
| ERR_UNKNOWN_PARTNER | 422 |
| ERR_ILL_LOAN_PERIOD_NOT_MET | 409 |
| ERR_DUPLICATE_RESERVATION | 409 |
| ERR_PAYMENT_EVENT_MISSING | 409 |
