# CounselGrid Holds & Collections API

CounselGrid is a backend for legal teams who need to keep people “on hold” for a matter, and then run evidence collections without quietly blowing past storage limits. The surface area is small: workspaces contain matters; matters contain custodians, holds, and collections. The unglamorous part is that it all shares the same storage pool, and “corrections” (release/void/purge/withdraw) are expected to unwind whatever side effects they caused.

### Workspaces, storage, and the thing called posture

Creating a workspace accepts a `name` and a `quota_bytes` number. Reading a workspace returns its `quota_bytes` and a current `posture` along with `bytes_reserved`, `bytes_stored`, and `bytes_available`.

`bytes_reserved` is capacity tied up by collections that are still in flight (collections that are `SUBMITTED`, `APPROVED`, or `IN_PROGRESS`). `bytes_stored` is capacity consumed by delivered evidence. `bytes_available` is what remains for new work. Clients should never observe totals that go negative, and the workspace should never appear to use more than `quota_bytes` in total.

Workspace posture is derived from what’s happening inside the workspace. It’s `LOCKDOWN` when at least one matter is effectively frozen (`FROZEN`). If it isn’t `LOCKDOWN`, it can still be `REVIEW` when it’s running close to full — “close” meaning `bytes_available` has dropped below ten percent of `quota_bytes`. Otherwise it’s `NORMAL`.

### Matters are where teams actually work

A matter belongs to exactly one workspace. Creating a matter takes a `title` and a `matter_type` of either `LITIGATION` or `INVESTIGATION`. Matters start with `status="DRAFT"`. Matter `status` is the simple lifecycle: `DRAFT`, `ACTIVE`, `CLOSED`. Status changes are driven via the matter state endpoint with `to_status`.

Reading a matter includes `status`, a derived `posture`, and storage rollups for that matter (`bytes_reserved`, `bytes_stored`). Those storage fields follow the same definitions as the workspace-level fields, but scoped to collections under that matter (so summing across matters matches the workspace totals).

Matter posture is separate from matter status; it’s meant to capture how constrained the matter is right now. If any hold on the matter is court-ordered (`is_court_ordered=true`) and currently `ACTIVE`, the matter posture is `FROZEN`. If it isn’t frozen, the matter posture is `REVIEW` when it has any in-flight work: at least one hold in `ISSUED`, or at least one collection in `SUBMITTED`, `APPROVED`, or `IN_PROGRESS`. Otherwise it’s `OPEN`.

A matter can only be moved from `DRAFT` to `ACTIVE` once it has at least one custodian whose `status` is `ACTIVE`. If the matter already contains any court-ordered holds, those holds are expected to already be `ACTIVE` before the matter can be activated.

Closing a matter is meant to be final. A matter can only be moved to `CLOSED` when it has no active hold obligations left and no in-flight collection work — in practice: no holds in `ISSUED`, `ACTIVE`, or `SUSPENDED`, and no collections in `SUBMITTED`, `APPROVED`, or `IN_PROGRESS`. Reopening is allowed by moving from `CLOSED` back to `ACTIVE`, but reopening doesn’t resurrect collection requests that were already withdrawn.

### Custodians (people) and what “purged” means

Custodians are the people whose data is in scope for holds and collections. Creating a custodian accepts `full_name` and `email`. Custodians start with `status="ACTIVE"`. Changing a custodian’s status uses the custodian state endpoint and `to_status`, with `ACTIVE`, `DEPARTED`, and `PURGED`.

Non-court-ordered work treats departed custodians as high-friction: non-court-ordered holds aren’t expected to be issued to departed custodians, and collection work that requires fresh access (moving a collection into `IN_PROGRESS`) is blocked while the custodian is departed. Court-ordered holds are the explicit exception: they can still be issued/advanced even if a custodian is departed.

Purging is treated as a correction with cascading effects. When a custodian becomes `PURGED`, the platform immediately stops treating them as eligible for new work, and it unwinds existing work where possible: any non-court-ordered holds that still include the custodian move to `RELEASED`, and any non-delivered collections for that custodian move to `WITHDRAWN`. Evidence that was already delivered stays stored; a purge does not retroactively delete delivered evidence.

A custodian can’t be purged while they are still covered by any court-ordered hold that is `ACTIVE`.

### Holds: basis, scope, and corrections

A hold ties custodians to a matter and captures a legal basis and scope. Creating a hold accepts `title`, `legal_basis`, `scope`, `is_court_ordered`, and `custodian_ids`.

`legal_basis` is one of `LITIGATION`, `REGULATORY`, or `CONTRACT`. `scope` is one of `ALL_DATA`, `EMAIL_ONLY`, `CHAT_ONLY`, or `DRIVE_ONLY`. Holds start in `DRAFT`. Hold status is one of `DRAFT`, `ISSUED`, `ACTIVE`, `SUSPENDED`, `RELEASED`, `VOID`, and hold status changes are driven via the hold state endpoint using `to_status`.

Legal basis is expected to fit the matter type: on `LITIGATION` matters, `LITIGATION` and `CONTRACT` are normal, and `REGULATORY` is only acceptable when the hold is court-ordered. On `INVESTIGATION` matters, `REGULATORY` and `CONTRACT` are normal, and `LITIGATION` is only acceptable when the hold is court-ordered.

Draft holds can be edited, but once a hold is issued it’s treated as locked for edits. Court-ordered holds also have extra restrictions: a court-ordered hold can’t be suspended.

Corrections cascade. Releasing or voiding a hold automatically withdraws collection requests underneath it that haven’t been delivered yet. Deliveries are not retroactively undone just because the hold was later released.

### Collections: reserving capacity, then turning it into stored evidence

Collections are evidence requests, tied to one custodian under one hold. Creating a collection accepts `hold_id`, `custodian_id`, `data_source`, and `estimated_bytes`. `data_source` is one of `EMAIL`, `CHAT`, or `DRIVE`.

Collections start in `DRAFT`. Collection status is one of `DRAFT`, `SUBMITTED`, `APPROVED`, `IN_PROGRESS`, `DELIVERED`, `WITHDRAWN`, `REJECTED`. Collection status changes are driven via the collection state endpoint using `to_status`. When moving a collection to `DELIVERED`, the request includes `actual_bytes`; that is what becomes stored for the workspace and the matter.

Collections enforce a few consistency relationships: the referenced hold and custodian are expected to belong to the same matter as the collection; the custodian must be included in the hold’s `custodian_ids`; a collection can only be submitted when the hold is currently `ACTIVE`; and the hold `scope` must cover the collection’s `data_source` (for example, `scope="EMAIL_ONLY"` covers `data_source="EMAIL"` but not `CHAT`).

Capacity is enforced through the collection lifecycle. When a collection becomes `SUBMITTED`, its `estimated_bytes` becomes reserved capacity. While it is `SUBMITTED`, `APPROVED`, or `IN_PROGRESS`, it continues to consume `bytes_reserved`. When it becomes `DELIVERED`, the reservation is replaced by stored evidence using `actual_bytes`. When it becomes `WITHDRAWN` or `REJECTED`, any reservation is released. Capacity checks are real checks: if a change would exceed available workspace capacity, the change is blocked and the workspace’s numbers don’t partially change.

Some restrictions show up indirectly through posture. In workspace `LOCKDOWN`, normal advancement of work is blocked; withdrawing in-flight work is still allowed, and releasing/voiding holds is still allowed. In workspace `REVIEW`, teams can still draft and submit work, but moving a collection forward to `APPROVED` or `IN_PROGRESS` is reserved for court-ordered holds.

Suspending a hold stops new collection work under that hold. When a non-court-ordered hold is suspended, any collections under that hold that haven’t started yet are withdrawn (`DRAFT`, `SUBMITTED`, `APPROVED`). Collections already `IN_PROGRESS` stay in progress, but they can’t be delivered until the hold is active again.

A collection that has been delivered is treated as evidence on file; it can’t be withdrawn or rejected after delivery.

### Consistency controls (Idempotency-Key, If-Match, etag)

Mutating calls use an `Idempotency-Key` header so client retries don’t create duplicate holds/collections or accidentally double-transition state.

Updates to existing resources use optimistic concurrency. Reading a resource returns an `etag`. Any call that changes an existing resource (a `PATCH` or any `.../state` transition) includes `If-Match` with that `etag`. If the `etag` is stale, the call is rejected rather than “best-effort” applied. `etag` is returned as a top-level field in the response envelope (`data.etag`) on reads.

### Errors and what tends to surface first

Errors are returned in the standard response envelope with `response_type="error"` and a `data.error_code`.

When multiple problems apply to the same request, the API tends to fail in a predictable order. Missing required headers (`Idempotency-Key` or `If-Match`) comes first. After that, wrong scoping or unknown IDs surface as `ERR_NOT_FOUND`. Then posture gates (`ERR_POSTURE_BLOCKED`), then impossible lifecycle transitions (`ERR_INVALID_STATE`), and finally the domain/business rule failures (quota, scope mismatch, and the rest).

Resource IDs are not treated as globally readable. If a client tries to access a matter/hold/collection through the wrong workspace (or the wrong matter path), it behaves like a missing resource.

### Minimal API surface

- POST /workspaces
- GET /workspaces/:workspace_id
- POST /workspaces/:workspace_id/matters
- GET /workspaces/:workspace_id/matters/:matter_id
- PATCH /workspaces/:workspace_id/matters/:matter_id
- POST /workspaces/:workspace_id/matters/:matter_id/state
- POST /workspaces/:workspace_id/matters/:matter_id/custodians
- GET /workspaces/:workspace_id/matters/:matter_id/custodians/:custodian_id
- POST /workspaces/:workspace_id/matters/:matter_id/custodians/:custodian_id/state
- POST /workspaces/:workspace_id/matters/:matter_id/holds
- GET /workspaces/:workspace_id/matters/:matter_id/holds/:hold_id
- PATCH /workspaces/:workspace_id/matters/:matter_id/holds/:hold_id
- POST /workspaces/:workspace_id/matters/:matter_id/holds/:hold_id/state
- POST /workspaces/:workspace_id/matters/:matter_id/collections
- GET /workspaces/:workspace_id/matters/:matter_id/collections/:collection_id
- PATCH /workspaces/:workspace_id/matters/:matter_id/collections/:collection_id
- POST /workspaces/:workspace_id/matters/:matter_id/collections/:collection_id/state

All responses use a standard envelope:

```json
{
  "response_type": "object | array | error",
  "data": { }
}
```

Required headers:
- `Idempotency-Key` on any POST/PATCH that creates or changes data
- `If-Match` on any `PATCH` and any `.../state` call that changes an existing resource

Error codes:
- ERR_BAD_REQUEST
- ERR_NOT_FOUND
- ERR_MISSING_IDEMPOTENCY_KEY
- ERR_MISSING_IF_MATCH
- ERR_IDEMPOTENCY_REPLAY_MISMATCH
- ERR_ETAG_MISMATCH
- ERR_POSTURE_BLOCKED
- ERR_INVALID_STATE
- ERR_QUOTA_EXCEEDED
- ERR_HOLD_SCOPE_MISMATCH
- ERR_HOLD_NOT_ACTIVE
- ERR_CUSTODIAN_NOT_IN_HOLD
- ERR_CUSTODIAN_DEPARTED
- ERR_CUSTODIAN_PURGED
- ERR_COURT_ORDERED_RESTRICTION
- ERR_MATTER_HAS_ACTIVE_HOLDS
- ERR_MATTER_HAS_PENDING_COLLECTIONS