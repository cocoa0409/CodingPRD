# DropBite Storefront API

DropBite is the “limited-run” side of a food delivery platform: think chef specials, pop-up collabs, or a small batch of dumplings that a storefront can only make a fixed number of times.

The core goal is simple: customers place orders against a limited `drop`, the kitchen commits to a fair subset when capacity is tight, and pickup happens in tidy `bundles` without silently breaking capacity or policy.

Everything here is scoped to a single `storefront`. There’s no shared state between storefronts.

## Storefronts: posture and ops runs

Storefronts have a `posture` because real kitchens have bad nights. Posture shows up on the storefront read and it’s the main “operating mode” that clients use to decide what to show customers.

- `OPEN` means the storefront is accepting new orders normally.
- `THROTTLED` means the storefront is still taking new orders, but only small ones (details below).
- `PAUSED` means the storefront has stopped taking new orders entirely, but it can still finish and hand off what’s already in motion.

DropBite doesn’t rely on wall clocks. The kitchen (or an ops process) runs explicit “waves” through `POST /storefronts/:storefront_id/run_ops`. Each run increments the storefront’s `ops_run_index`, and it’s when two big things happen:

1) The storefront’s posture may change based on recent waste.
2) Orders get “settled” for each live drop (accepting from the queue, or moving people to a waitlist).

### What counts as waste (and why it matters)

Voiding an order is sometimes just cleanup (“we never started cooking”) and sometimes it means food was wasted (“it was already in the kitchen”). DropBite treats a void as a *waste void* only when the order was already `IN_KITCHEN` or `READY`.

Waste voids are counted between ops runs. On the next `run_ops`:
- If there were no waste voids since the last run, the storefront becomes `OPEN`.
- If there was exactly one waste void, the storefront becomes `THROTTLED`.
- If there were two or more waste voids, the storefront becomes `PAUSED`.

In other words: one bad miss slows the storefront down; two stops new intake until things stabilize.

### What posture changes in practice

Posture affects multiple workflows in a way that should feel obvious to clients:

- In `PAUSED`, the storefront doesn’t accept new orders (including creating new `orders`), but customers can still read their state and perform cleanup actions like cancelling a pending order. Kitchens can still progress already-accepted work and create pickup bundles for `READY` orders.
- In `THROTTLED`, customers can still place orders, but the maximum `quantity` per order is 2 servings. If an order is bigger than that, it doesn’t disappear; it becomes `NEEDS_REVIEW` until the customer trims it down.

## Drops: limited batch supply, with clean pause/close behavior

A `drop` is a limited batch of a menu item. Creating a drop accepts a `title` and `servings_total`. Drops start as `PLANNED` while the kitchen gets set up. When the storefront is ready to take real orders, the drop is switched to `LIVE`.

A drop read includes a derived `servings_remaining`. This value never goes negative, and it updates immediately when orders are accepted, voided, or picked up. It only reflects committed kitchen work (not drafts or people waiting in line).

Drop status is one of:
- `PLANNED`
- `LIVE`
- `PAUSED`
- `CLOSED`

### Pausing a drop

Pausing is for “we can’t promise anything new right now” (ingredient shortage, equipment issue, etc.). When a `LIVE` drop becomes `PAUSED`, any order that was still in the intake pipeline (`SUBMITTED` or `WAITLISTED`) flips into `NEEDS_REVIEW` immediately. That’s intentional: the customer has to actively re-confirm after a pause.

When a drop returns to `LIVE`, those `NEEDS_REVIEW` orders stay `NEEDS_REVIEW` until the customer resubmits them. Their place in line (`ticket_no`) doesn’t change.

### Closing a drop

Closing is the end of the batch. A `CLOSED` drop doesn’t accept new submissions. Customers who never made it into the committed set shouldn’t be stuck forever; during the next `run_ops`, any order still in `SUBMITTED`, `WAITLISTED`, or `NEEDS_REVIEW` for a closed drop becomes `CANCELLED`.

Closing doesn’t stop fulfillment: orders that were already accepted can still move through the kitchen and pickup.

### Adjusting `servings_total`

Sometimes the kitchen finds extra capacity, sometimes it loses some. A drop’s `servings_total` can move up or down while it isn’t closed, but there’s a hard integrity rule: you can’t reduce `servings_total` below what the kitchen has already committed to (orders in `ACCEPTED`, `IN_KITCHEN`, `READY`, or `PICKED_UP`). If a change would violate that, it fails with `ERR_CONSTRAINT_VIOLATION` and nothing changes.

Drop updates use optimistic concurrency: a drop includes a `version`, and updates use the `If-Match` header.

## Orders: drafts, queue settlement, and kitchen progression

An `order` starts as a customer’s draft. Creating an order accepts:
- `drop_id`
- `customer_ref` (an external reference from the client)
- `quantity`
- an optional `note`

Orders also get a `ticket_no`. Ticket numbers are the fairness primitive: when capacity is limited, earlier tickets win. DropBite enforces “no jumping the line”: if there isn’t enough capacity for the next ticket’s `quantity`, later tickets don’t leapfrog it in the same ops run.

### Order status

Orders move through these states:

- `DRAFT`
- `SUBMITTED`
- `WAITLISTED`
- `NEEDS_REVIEW`
- `ACCEPTED`
- `IN_KITCHEN`
- `READY`
- `PICKED_UP`
- `CANCELLED`
- `VOIDED`

### One order per customer per drop (while it matters)

For a given `drop_id` and `customer_ref`, there can only be one “active” order at a time. An order is considered active while it’s in `DRAFT`, `SUBMITTED`, `WAITLISTED`, `NEEDS_REVIEW`, `ACCEPTED`, `IN_KITCHEN`, or `READY`. Once it’s `CANCELLED`, `VOIDED`, or `PICKED_UP`, it no longer blocks a new order for that customer on that drop.

### Quantity rules (simple on the surface, cross-cutting in reality)

Quantity limits are posture-driven:
- In `OPEN`, the maximum `quantity` is 6.
- In `THROTTLED`, the maximum `quantity` is 2.
- In `PAUSED`, new orders aren’t accepted.

These limits apply when creating an order and when submitting it. If the storefront becomes `THROTTLED` after an order was already submitted, the order isn’t silently resized; it becomes `NEEDS_REVIEW` until the customer updates it to a compliant quantity and resubmits.

### Editing and concurrency

Order edits are versioned. Reading an order returns its `version`. Updates use `PUT` with `If-Match`.

Editing follows the common-sense lifecycle:
- In `DRAFT`, both `quantity` and `note` can be changed.
- In `SUBMITTED`, `WAITLISTED`, or `NEEDS_REVIEW`, `note` can be changed and `quantity` can only be reduced (increasing the ask would be unfair).
- In `ACCEPTED` or later, the order is locked.

### Submitting, settling, and acceptance

Submitting is the customer’s “I’m in.” Submitting moves an order into the intake pipeline:
- `DRAFT` → `SUBMITTED`
- `NEEDS_REVIEW` → `SUBMITTED` (this is how customers re-confirm after a pause or throttle review)

A submission only succeeds when the drop is `LIVE` and the storefront posture allows intake.

Settlement happens at `run_ops`. For each `LIVE` drop, the platform looks at orders in `SUBMITTED` and `WAITLISTED` (in `ticket_no` order) and commits as many as it can without exceeding supply. Committed orders become `ACCEPTED` and reduce the drop’s `servings_remaining`.

If the platform hits an order whose `quantity` won’t fit in the remaining supply, it becomes `WAITLISTED` (or stays waitlisted), and later tickets don’t get accepted in that run for that drop. “No jumping the line” is more important than squeezing every last serving out of a wave.

### Cancelling vs voiding (the correction story)

Customers can cancel pending orders. `POST /.../cancel` works while the order is still in the intake states (`DRAFT`, `SUBMITTED`, `WAITLISTED`, `NEEDS_REVIEW`). After the kitchen has accepted the work, customers can’t cancel; the storefront uses voiding.

Voiding is an ops correction. `POST /.../void` moves:
- `ACCEPTED` → `VOIDED`
- `IN_KITCHEN` → `VOIDED`
- `READY` → `VOIDED`

Voiding immediately releases the order’s servings back into the drop (increasing `servings_remaining`) and, if the order had already been added to a pickup bundle, it’s removed from that bundle as part of the same correction.

As described earlier, voiding from `IN_KITCHEN` or `READY` is a waste void and influences storefront posture on the next ops run.

### Advancing kitchen state

The kitchen progresses accepted work with `POST /.../advance`:
- `ACCEPTED` → `IN_KITCHEN`
- `IN_KITCHEN` → `READY`
- `READY` → `PICKED_UP`

Pickup is gated by bundles (next section): an order can only become `PICKED_UP` when it belongs to a sealed pickup bundle.

## Pickup bundles: clean handoff without chaos

A `bundle` is a pickup packet for couriers. Bundles are per drop: creating a bundle includes a `drop_id` and `max_orders`.

A bundle includes an `order_ids` list and a `status`:
- `DRAFT`
- `SEALED`

Adding an order to a bundle requires:
- The order is `READY`
- The order belongs to the same `drop_id` as the bundle
- The bundle is still `DRAFT`
- The bundle has not exceeded `max_orders`
- The order is not already in a different bundle

Sealing a bundle is the handoff moment: it flips `status` to `SEALED`. After a bundle is sealed, new orders cannot be added (`ERR_BUNDLE_LOCKED`), but corrections still unwind. If a `READY` order is voided after being bundled, it’s removed from `order_ids` even if the bundle was already sealed.

As noted above, the `READY` → `PICKED_UP` transition is only allowed when the order is in a `SEALED` bundle.

## Makegoods: automatic credits for a ready-void

When a `READY` order is voided, the customer was effectively promised pickup. DropBite automatically issues a `makegood` record for that order, returned as `makegood_id` on the void response.

A makegood read includes:
- `order_id`
- `amount_cents`
- `status`

The amount rule is intentionally simple: a ready-void earns five dollars per serving, capped at twenty dollars total (returned as cents in `amount_cents`). Voids from `IN_KITCHEN` do not create a makegood; only `READY` does.

## Retries, versions, and predictable failures

DropBite gets used in real checkout flows where customers retry, apps resubmit, and ops hits the same button twice during a rush. The system stays sane by being consistent about “did this already happen?” and “what does this error mean?” across the whole surface.

### Versions on updates

Updates use optimistic concurrency:
- `PUT` and `PATCH` require `If-Match`.
- If the `If-Match` value doesn’t match the current `version`, the update fails with `ERR_VERSION_CONFLICT`.

### When multiple things are wrong

DropBite surfaces errors in a predictable order:
1) Missing required headers (`ERR_MISSING_IF_MATCH`)
2) Unknown IDs / wrong storefront (`ERR_NOT_FOUND`)
3) Invalid lifecycle action (`ERR_INVALID_STATE`)
4) Business rule blockers (like `ERR_STORE_PAUSED`, `ERR_DROP_PAUSED`, `ERR_DROP_CLOSED`, `ERR_DROP_NOT_LIVE`, `ERR_QUANTITY_LIMIT_EXCEEDED`, `ERR_BUNDLE_FULL`, `ERR_BUNDLE_LOCKED`, `ERR_CONSTRAINT_VIOLATION`)
5) Everything else malformed (`ERR_BAD_REQUEST`)

### Response envelope

Responses use an envelope with `response_type` and `data`. Errors use `response_type="error"` and include `error_code` and `message` in `data`.

## Endpoints

| Method | Path                                                     |
| ------ | -------------------------------------------------------- |
| POST   | /storefronts                                             |
| GET    | /storefronts/:storefront_id                              |
| POST   | /storefronts/:storefront_id/run_ops                      |
| POST   | /storefronts/:storefront_id/drops                        |
| GET    | /storefronts/:storefront_id/drops/:drop_id               |
| PATCH  | /storefronts/:storefront_id/drops/:drop_id               |
| POST   | /storefronts/:storefront_id/orders                       |
| GET    | /storefronts/:storefront_id/orders/:order_id             |
| PUT    | /storefronts/:storefront_id/orders/:order_id             |
| POST   | /storefronts/:storefront_id/orders/:order_id/submit      |
| POST   | /storefronts/:storefront_id/orders/:order_id/cancel      |
| POST   | /storefronts/:storefront_id/orders/:order_id/advance     |
| POST   | /storefronts/:storefront_id/orders/:order_id/void        |
| POST   | /storefronts/:storefront_id/bundles                      |
| GET    | /storefronts/:storefront_id/bundles/:bundle_id           |
| POST   | /storefronts/:storefront_id/bundles/:bundle_id/add_order |
| POST   | /storefronts/:storefront_id/bundles/:bundle_id/seal      |
| GET    | /storefronts/:storefront_id/makegoods/:makegood_id       |

## Appendix: errors and headers

Required headers:

* `If-Match` (all `PUT` and `PATCH` requests)

Error codes:

* `ERR_BAD_REQUEST`
* `ERR_NOT_FOUND`
* `ERR_MISSING_IF_MATCH`
* `ERR_VERSION_CONFLICT`
* `ERR_INVALID_STATE`
* `ERR_STORE_PAUSED`
* `ERR_DROP_NOT_LIVE`
* `ERR_DROP_PAUSED`
* `ERR_DROP_CLOSED`
* `ERR_QUANTITY_LIMIT_EXCEEDED`
* `ERR_CONSTRAINT_VIOLATION`
* `ERR_BUNDLE_FULL`
* `ERR_BUNDLE_LOCKED`