# SiteLedger — Construction Project Management API

SiteLedger is a backend for running a construction project as a set of “work items” that crews plan, start, and finish. The whole point is to let the field keep moving without silently drifting out of budget or compliance: the project has a labor plan, permits that can be granted/revoked by trade, inspections that can pass/fail, and change orders that adjust scope or budget without rewriting history.

Everything lives under a project. Clients mostly care about two reads: the project’s `posture` (how restrictive the site is right now) and, per work item, whether it’s `is_startable` and why (`start_blockers`).

Creating a project takes a `name` and a `labor_budget_hours`. Each resource (project, work item, permit, inspection, change order) is uniquely identified by an `id` field. Reading the project returns the current `posture`, a lightweight `permits` list, and labor accounting fields (`labor_reserved_hours`, `labor_committed_hours`, `labor_used_hours`, `labor_available_hours`). Those numbers are never stale: if a request succeeds, a follow-up `GET` reflects the new totals immediately.

Labor is accounted for in three buckets. A work item in `READY` reserves its `estimated_hours` into `labor_reserved_hours`. A work item in `IN_PROGRESS` commits its `estimated_hours` into `labor_committed_hours`. A work item in `DONE` contributes its reported `actual_hours` into `labor_used_hours` (and stops occupying reserved/committed capacity). `labor_available_hours` is whatever remains inside `labor_budget_hours` after those buckets are accounted for. The system never allows labor availability to go negative: if a move to `READY` would over-reserve, or if completing with a given `actual_hours` would exceed the plan, the request fails with `ERR_LABOR_BUDGET_EXCEEDED` and the work item stays where it was (e.g. completion leaves it `IN_PROGRESS`).

Work items are the unit of field execution. Creating one takes `title`, `trade`, `zone`, `criticality`, and `estimated_hours` and starts it in `status: DRAFT`. The work item lifecycle is `DRAFT` → `READY` → `IN_PROGRESS` → `DONE`, with `CANCELLED` as a terminal outcome from `DRAFT`, `READY`, or `IN_PROGRESS`. `DRAFT` is planning and does not reserve labor. `READY` is planned and holding capacity. `IN_PROGRESS` is active work holding capacity. `DONE` reports `actual_hours` and releases committed capacity. `CANCELLED` removes the item from active scope (it no longer holds hours and stops affecting posture).

When a client reads a work item, it gets `is_startable` and `start_blockers` in addition to the planning fields and `status`. `start_blockers` is a list of strings; when present it uses values from `POSTURE`, `PERMIT`, `ZONE`, `CHANGE_ORDER`, `SAFETY`. A work item can flip between startable and not startable as the project changes; that’s expected, and these derived fields should be kept accurate after any relevant change (permit decisions, inspection results, posture changes, change order transitions, cancellations).

Starting work is where the project’s cross-cutting rules show up. A work item is only startable while it is `READY`. If the project is in `STOP_WORK`, field work doesn’t advance. If the project is in `REVIEW`, starting a work item requires that item’s `latest_safety_status` to be `PASSED`. Starting is also blocked when the item is frozen due to an approved change order. Zone access matters too: a project can have at most one non-`GENERAL` work item in `IN_PROGRESS` per zone at a time. `GENERAL` work is exempt: it can be started even when a non-`GENERAL` item is already in progress in that same zone, and it does not “occupy” the zone for other starts. Zones are represented as values like `ZONE_A`, `ZONE_B`, `ZONE_C`.

Trades are `ELECTRICAL`, `PLUMBING`, `STRUCTURAL`, and `GENERAL`. `GENERAL` work does not require a permit. All other trades require the project to have a current permit for that `trade` in `GRANTED` before moving a work item to `READY`; otherwise the move to `READY` is rejected with `ERR_PERMIT_REQUIRED`. Permits are tracked per project and trade; creating a permit sets `status: REQUESTED`, and a manager later decides it via a permit decision (`decision` is `GRANT` or `REVOKE`) which moves it to `GRANTED` or `REVOKED`. For each trade, the “current” permit is simply the most recently created permit for that trade. Because of that, creating a new permit for a trade where the current permit is not revoked is rejected with `ERR_PERMIT_ALREADY_EXISTS`. If the current permit is revoked, a replacement permit is allowed but must include `replaces_permit_id` pointing at the revoked permit; otherwise it is rejected with `ERR_PERMIT_REPLACEMENT_REQUIRED`.

Inspections are always attached to a `work_item_id`. An inspection has a `kind` of `SAFETY` or `QUALITY`. Creating an inspection starts it as `PLANNED`. Submitting uses an `outcome` of `PASSED` or `FAILED`, which sets its `status` accordingly. Managers can void an inspection, which sets `status: VOIDED` (and a voided inspection is ignored when determining “current” inspection state). For each work item and kind, the “current” inspection is the latest one that is not `VOIDED`. To avoid duplicate scheduling, a work item can only have one `PLANNED` inspection of a given `kind` at a time; attempts to create a second planned inspection fail with `ERR_INSPECTION_ALREADY_PLANNED`.

Inspection results affect both posture and lifecycle gates. A failed `SAFETY` inspection on an active item puts the project in `STOP_WORK` until a newer (non-voided) safety inspection on that item is submitted as `PASSED`, or the item stops being active (e.g. it becomes `CANCELLED`). A failed `QUALITY` inspection blocks completion of that work item with `ERR_QUALITY_FAILED_BLOCKING`. Work items have a `criticality` of `STANDARD` or `CRITICAL`; for `CRITICAL` items, completion is only allowed when `latest_quality_status=PASSED`; otherwise completion is rejected with `ERR_QUALITY_FAILED_BLOCKING`. Quality failures also contribute to project restriction: two or more distinct active work items with `latest_quality_status=FAILED` put the project in `REVIEW`.

Projects carry a `posture` of `OPEN`, `REVIEW`, or `STOP_WORK`. Posture is derived and recalculates as permits, inspections, budgets, and “active work” change. “Active work” means work items that are not `DONE` and not `CANCELLED`. Inspection impact is based on the latest (non-`VOIDED`) inspection per work item and `kind`. Permit impact is based on the current permit per trade. Posture is determined as follows:
1) `STOP_WORK` when any active work item has `latest_safety_status=FAILED`.
2) `STOP_WORK` when a `trade` has a current permit in `REVOKED` and there is any active work item for that trade in `READY` or `IN_PROGRESS`.
3) Otherwise `REVIEW` when two or more distinct active work items have `latest_quality_status=FAILED`.
4) Otherwise `REVIEW` when `labor_available_hours` drops under 20 hours.
5) Otherwise posture is `OPEN`.

When a project is in `STOP_WORK`, crews don’t move work forward: creating work items, moving work items to `READY`, starting, and completing are blocked with `ERR_POSTURE_BLOCKED`. Recovery actions still have to be possible: work can still be cancelled, permits can still be decided, inspections can still be created/submitted (and existing inspections can be voided), and change orders can still be approved/applied/cancelled.

Change orders are how the plan changes without silently editing work items in place. Creating a change order takes `work_item_id` and `summary`, and can optionally include `labor_budget_hours_delta` and/or a scope change (`new_estimated_hours`, `new_trade`, `new_zone`). A change order starts `status: PROPOSED`. A work item can have at most one open change order at a time (“open” means `PROPOSED` or `APPROVED`); attempts to open another are rejected with `ERR_CHANGE_ORDER_CONFLICT`.

Approving a change order sets `status: APPROVED` and freezes the associated work item until the change order is applied or cancelled. Frozen work items don’t advance (no ready/start/complete); attempts fail with `ERR_WORK_ITEM_FROZEN`, and the frozen condition can appear in `start_blockers` as `CHANGE_ORDER`. Cancellation of a work item remains an escape hatch; when a work item is cancelled, any open change order for it (in `PROPOSED` or `APPROVED`) becomes `CANCELLED`.

Applying requires the change order to be `APPROVED` (otherwise `ERR_CHANGE_ORDER_NOT_APPROVED`) and on success sets `status: APPLIED`. Applying a budget change updates the project’s `labor_budget_hours`, but it cannot drop the budget below what is already reserved/committed/used; if it would, apply is rejected with `ERR_LABOR_BUDGET_EXCEEDED` and nothing changes. Applying a scope change (`new_estimated_hours`, `new_trade`, `new_zone`) is only allowed while the work item is still planning (`DRAFT` or `READY`); if work is already active (`IN_PROGRESS`) or finished (`DONE`), apply is rejected with `ERR_SCOPE_CHANGE_NOT_ALLOWED`. When a scope change is applied, the work item resets back to `DRAFT` (with the new planning values) and releases any reserved hours it was holding. Because the plan changed, inspections tied to that work item stop being meaningful for posture; in effect, applying a scope change voids that work item’s inspection trail for posture purposes (clients will see `latest_safety_status` / `latest_quality_status` drop out accordingly).

Cancelling a change order is allowed from `PROPOSED` or `APPROVED` and sets `status: CANCELLED`. If it was approved, cancelling also unfreezes the work item immediately.

Every request includes an `X-Actor-Role` header and is evaluated as one of `FOREMAN`, `INSPECTOR`, or `MANAGER`. If the role header is missing, the request fails with `ERR_UNAUTHENTICATED`. If the role is present but not allowed for the operation, the request fails with `ERR_FORBIDDEN`.

All `POST` requests use an `Idempotency-Key`. Replaying the same `POST` with the same key returns the original outcome (including failures). Replaying the same key with a meaningfully different request returns `ERR_IDEMPOTENCY_REPLAY_MISMATCH`. Work item transitions and change order transitions use `If-Match` with the last seen `etag` from a `GET`; missing `If-Match` returns `ERR_MISSING_IF_MATCH` and a stale `If-Match` returns `ERR_ETAG_MISMATCH`.

All resources live under a project. IDs are not portable across projects; referencing an ID under the wrong project is treated as `ERR_NOT_FOUND`.

When multiple problems are present, the API uses a single global precedence: authentication (`ERR_UNAUTHENTICATED`) comes first; then missing idempotency for `POST` (`ERR_MISSING_IDEMPOTENCY_KEY`); then idempotency replay mismatch (`ERR_IDEMPOTENCY_REPLAY_MISMATCH`); then unknown IDs/wrong project (`ERR_NOT_FOUND`); then role not allowed (`ERR_FORBIDDEN`); then posture restriction (`ERR_POSTURE_BLOCKED`); then missing/stale `If-Match` where required (`ERR_MISSING_IF_MATCH`, `ERR_ETAG_MISMATCH`); then invalid lifecycle action (`ERR_INVALID_STATE`); and only then domain rule failures (budget/permits/zones/etc.).

All responses use the same envelope:

```json
{
  "response_type": "object | error",
  "data": { }
}
````

Errors set `response_type` to `error` and include `error_code` and `message` in `data`.

## Endpoints

POST /projects
GET /projects/:project_id

POST /projects/:project_id/work_items
GET /projects/:project_id/work_items/:work_item_id
POST /projects/:project_id/work_items/:work_item_id/ready
POST /projects/:project_id/work_items/:work_item_id/start
POST /projects/:project_id/work_items/:work_item_id/complete
POST /projects/:project_id/work_items/:work_item_id/cancel

POST /projects/:project_id/permits
POST /projects/:project_id/permits/:permit_id/decide

POST /projects/:project_id/inspections
POST /projects/:project_id/inspections/:inspection_id/submit
POST /projects/:project_id/inspections/:inspection_id/void

POST /projects/:project_id/change_orders
GET /projects/:project_id/change_orders/:change_order_id
POST /projects/:project_id/change_orders/:change_order_id/approve
POST /projects/:project_id/change_orders/:change_order_id/apply
POST /projects/:project_id/change_orders/:change_order_id/cancel

## Appendix: error codes

* ERR_BAD_REQUEST
* ERR_UNAUTHENTICATED
* ERR_FORBIDDEN
* ERR_NOT_FOUND
* ERR_MISSING_IDEMPOTENCY_KEY
* ERR_IDEMPOTENCY_REPLAY_MISMATCH
* ERR_MISSING_IF_MATCH
* ERR_ETAG_MISMATCH
* ERR_POSTURE_BLOCKED
* ERR_INVALID_STATE
* ERR_LABOR_BUDGET_EXCEEDED
* ERR_PERMIT_ALREADY_EXISTS
* ERR_PERMIT_REPLACEMENT_REQUIRED
* ERR_PERMIT_REQUIRED
* ERR_ZONE_OCCUPIED
* ERR_INSPECTION_ALREADY_PLANNED
* ERR_WORK_ITEM_FROZEN
* ERR_QUALITY_FAILED_BLOCKING
* ERR_CHANGE_ORDER_CONFLICT
* ERR_CHANGE_ORDER_NOT_APPROVED
* ERR_SCOPE_CHANGE_NOT_ALLOWED