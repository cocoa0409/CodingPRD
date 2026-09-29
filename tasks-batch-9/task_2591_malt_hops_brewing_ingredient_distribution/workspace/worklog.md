
## Step 8: Finalize PRD — 2026-09-03T20:50:00.000Z

Verified: three edit sites only, file intact (465 → 467 lines).

## Line counts
PRD.md 465 → PRD_FINALIZED.md 467 (+2 lines, +0.43%). Three modified/inserted sites, no deletions.

## Changes
- **§2.1 (Identity binding) — insert** — a `Brewer` actor is *not* scope-checked on the `Brewer` entity itself: `GET /brewers/{id}` is readable for any brewery, and an unresolvable id there reports `ERR_BREWER_NOT_FOUND`, never `ERR_BREWER_SCOPE_VIOLATION` — `implementation/routes/brewers.py:67-71` (no `scope_brewer` call).
- **§2.5 (Common resource properties) — insert** — pinned the serialization of instants other than `created_at`/`updated_at`: server-stamped/derived instants render as ISO 8601 UTC with three fractional digits and a `Z`; client-supplied instants are echoed back verbatim, including where copied onto another field (`last_reading_at`) — `implementation/db.py:93-110` (`set_dt`/`dt_out` raw echo), `implementation/util.py:79-87` (`fmt_iso`).
- **§3.8 (Adding lines) — revise** — added the `Brewer`-actor carve-out: the §2.1 ownership scope on the named `hop_contract_id` is evaluated before the `ERR_CONTRACT_BREWER_MISMATCH` coherence check, so a Brewer naming a rival's contract gets `ERR_BREWER_SCOPE_VIOLATION`; the desk path still reports the 422 — `implementation/routes/orders.py:160-169`.

## Per-edit pre-edit search log

**Edit 1 — §2.1 brewer-entity scope**
(a) Subject: whether the `Brewer` role is scope-checked when a brewery is addressed by id.
(b) Enumerated: `grep -rn "scope_brewer"` across all of `implementation/` (24 hits) plus every `@bp.get`/`@bp.post` handler list in `routes/`. Read `routes/brewers.py` (all 5 endpoints: create is `CreditManager`/`PlatformAdmin`; `GET /brewers/{id}` unscoped `ALL_ROLES`; credit-profile, payments, volume-adjustments are non-Brewer roles), `middleware.py:63-69`, `routes/orders.py` (order/line get + list are scoped, list also filters by actor), `routes/contracts.py:139-187`, `routes/yeast.py:178-329`, `routes/offers.py`, `routes/coldchain.py` handler inventory.
(c) Adjustment: kept the wording strictly limited to the `Brewer` entity and `GET /brewers/{id}`. Deliberately did **not** phrase it as "every other brewer-referencing resource *is* scoped", because `GET /hop-contracts` (`routes/contracts.py:147-187`) performs no scope check and no actor filtering at all — a universal claim there would have been a new mismatch. Also stated the 404 explicitly since `must_exist` runs before any scope logic.

**Edit 2 — §2.5 instant serialization**
(a) Subject: the wire format of every datetime field in every response.
(b) Enumerated: `grep -rn "set_dt|clock_iso|_raw"` across `implementation/` (every call site), `db.py:93-110` (`set_dt`/`dt_out`), `util.py:79-87` (`fmt_iso`), `validation.py:174-184` (`f_dt` returns `(datetime, raw)`), and all of `serialize.py` (every `dt_out` usage: program `contract_open_date`/`harvest_report_due_date`/`harvest_reported_at`, contract windows, offer `responded_at`, lot `received_at`, job `pitch_date`/`ready_at`, order `requested_ship_date`/`invoiced_at`/`delivered_at`, shipment `stage_from`/`stage_until`/`last_reading_at`, reading `recorded_at`/`created_at`), plus `cascades.py:237` (replacement job pitch date, no raw), `routes/contracts.py:272-282` (successor window shifted, no raw), `routes/malt.py:121-123` (`received_at` both branches), `routes/coldchain.py:306-312` (`last_reading_at` inherits the reading's raw), `routes/clock.py:19` + `db.py:65-66` (clock echo returns the raw string).
(c) Adjustment: the first draft was a single universal "all server timestamps carry three fractional digits" sentence. That would have mis-described the six client-supplied fields and the clock echo, so it was widened into two clauses — server-derived → canonical three-digit form; body-supplied → verbatim echo — and explicitly covered the two mixed cases (`received_at` defaulted vs supplied, `last_reading_at` copied from the reading).

**Edit 3 — §3.8 contract-brewer mismatch vs brewer scope**
(a) Subject: the error a caller sees when an added line names a contract owned by another brewery.
(b) Enumerated: `routes/orders.py:135-238` (`add_line`: order scope at 154, body-id resolution at 155-158, contract scope at 162, coherence at 165-169, order-state at 210, minimum at 234), `routes/orders.py:267-283` (`remove_line`), `:352-459` (`confirm_order` — reads contracts only via already-attached line references, no cross-brewery path), `middleware.py:63-69`, and every other `scope_brewer` contract call site (`routes/contracts.py:199`, `routes/offers.py:121,163` — all derive the brewer from the contract, so none can report the 422).
(c) Adjustment: dropped an explicit "at priority 6" from the clause. Impl resolves *all* body ids (`hop_variety_id`, `malt_lot_id`, `yeast_propagation_job_id`) before the contract scope check, so a rival contract combined with a bogus variety id yields a 404, not the 403 a literal priority-6-before-7 reading demands. "Is evaluated first" keeps the claim to exactly what impl does — scope before the coherence check — leaving that pre-existing ordering question under-determined rather than asserting something false.

## Items deliberately not patched
- `settled_at` — the field does not exist anywhere in `implementation/` (`grep` returns 0 hits; `routes/programs.py:112-132` stamps nothing on settle). PRD is silent and impl is silent, so a fresh implementer stays aligned; adding prose would have invented behavior.
- `expected_status=201` fixes in `test_09`/`test_14` — `routes/coldchain.py:170` and `routes/orders.py:88` already return 201, which §4 pins verbatim.
- `test_01` `7568 → 7432` — pure test arithmetic error (178432 − 171000); §3.8 step eleven already determines it.
- `fixtures.py` pitch-rate default — fixture bug; `routes/yeast.py:136-141` requires the field, exactly as §3.6 states.
- `test_18` `credit_terms_days 60 → 45` — §3.1 already declares the `0/15/30/45` enum and `routes/brewers.py:80-82` enforces it.
