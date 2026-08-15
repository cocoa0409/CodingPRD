# Worklog — task_1916_scenic_shop_set_fabrication

## Step 1: Create Task Directory — 2026-08-15T00:31:00.000Z

Directory `tasks/task_1916_scenic_shop_set_fabrication/` and `workspace/` pre-created by the pipeline launcher (Step 1 marked already done); no index scan performed.

## Step 2: Generate Scaffold — 2026-08-15T01:12:00.000Z

Scaffold generation complete for task 1916 (Scenic Shop & Set Fabrication). All three files written and verified.

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1916_scenic_shop_set_fabrication/SCAFFOLD.yaml` (§1.0–§1.7 only; no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1916_scenic_shop_set_fabrication/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1916_scenic_shop_set_fabrication/SCAFFOLD_CORNER_DESIGN.yaml` (single top key `scaffold_corner_design`)

**Counts:**
- Entities: 13 (Shop, Client, DesignPackage, Takeoff, TakeoffLine, Bid, Production, EngineeringReview, FinishSample, ChangeOrder, BayReservation, StockItem, TransportPlan)
- State machines: 10 (four cyclic: Bid counter/revise negotiation loop, EngineeringReview revision loop, FinishSample reject/resubmit loop, StockItem ACTIVE⇄DEPLETED; Production with IN_BUILD⇄ON_HOLD revert)
- Calculations: 7 (incl. dual-variant bid ROM vs detailed pricing, static vs dynamic safety factor, replacement vs recovery stock valuation; CO price with posture/overtime/rush-cap branches; per-line rounding pinned; pre-discount tier keying pinned)
- Endpoints: 65 (incl. `POST /scenic/_clock/set-current-utc` with the mandated 2026-08-01T00:00:00Z default)
- Errors: 31 (all referenced by ≥1 validation/transition, all exercised by ≥1 test instance)
- Roles: 7 (ClientPM is entity_backed:Client; six opaque shop/staff roles; segregation-of-duties on review approve vs preparer)
- §1.8 instances: 27 (9 rules × 3 — max differentiation: 3 entity domains for dual-variant, all 3 combinatorial modes a/b/c, 3 different cyclic entities, cascades of depth 4/3/2 from 3 distinct triggers, 3 distinct validation-priority category pairs, 3 boundary metrics on 3 endpoints, 3 cross-entity pairs, 3 interval semantics (half-open adjacency / aggregate fleet capacity / minimum-gap buffer), 3 conserved quantities (stock units, production price, shop capacity hours); 3 OCC concurrency rules with `${var}`-bound version payloads)
- §1.9 instances: 60 total = 56 active + 4 `excluded_because` stubs (all 7 roles have denial tests, all 31 errors triggered, OCC ×3, soft-delete, pagination+filter, epoch expiry, auth-before-existence priority, empty-set finish gate)

**Verification:** every formula-derived assert literal was executed in Python against the pinned formulas (e.g., detailed bid 1240800, rounding-order 28768 vs 28766, tier-boundary 637560/667920, CO TIGHT+rush 662000, rush cap 156000 at dd −6 and −7, SF 1.5 boundary pass / automation 1.0 fail, inventory 29375). Forbidden race vocabulary: clean. Lint verdict verbatim:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(690 calls scanned across §1.8+§1.9; endpoint count 65, entities 13, 27 + 56 active instances.) Two lint iterations were needed: first fixed 7 FK-reverse-reachability gaps by adding 5 GET-by-id endpoints plus `production_id?` on the bids list; a YAML flow-list quoting issue in corner `grounds:` was fixed by converting to block lists. No sibling tasks were consulted at any point.

## Step 3: Copy Shared Files — 2026-08-15T01:13:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1916_scenic_shop_set_fabrication/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T01:18:00.000Z

All checks pass. The PRD is complete and written to `/home/ubuntu/github/CodingPRD/tasks/task_1916_scenic_shop_set_fabrication/workspace/PRD.md`.

## Summary

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_1916_scenic_shop_set_fabrication/workspace/PRD.md`

- **Line count:** 313 lines
- **Section count:** 5 top-level sections (Introduction, Global Specifications, Business Logic & Workflows, Endpoint Definitions, Error Code Catalogue) with 17 subsections (10 in §2 including the verbatim §2.2 response-structure block, 7 in §3)
- **§4 endpoint table:** 67 rows, 4 columns (Method / Path / Description / Authorized Role)
- **§5 error table:** 31 error IDs, 2 columns (Error ID / HTTP Status Code)

**Hard-contract verification results (all PASS):**

- **Contract 1 (Field-Name Coverage):** 93/93 entity fields present in backticks; 74/74 endpoint input identifiers present; 13/13 path params present (inside §4 path backticks); 31/31 error IDs present; all 44 state/enum values present (`ACCEPTED` gap found on first pass and repaired). 0 missing.
- **Contract 2 (Rule Coverage):** All 12 validation-priority tiers expressed as an ordered cascade in §2.6; all 3 OCC rules expressed in §2.8 with write capability, `expected_production_version` / `expected_takeoff_version` / `expected_stock_item_version`, and the exact 412 error IDs; all state-machine transitions named with preconditions paired to error IDs and side effects stated (including the change-order approval cascade's per-step `version` increments, bay auto-release, posture recompute, and rejection-as-compensating-invariant anchor); all 7 calculations rendered as precise reconstruction-safe prose (per-line rounding before summation, pre-discount volume-tier keying at 500000 cents / 500 bp, ROM 28-day / 12500 bp urgency with 9000/14000/22000 complexity rates, safety factors 1.50 / 2.00 with amplification-before-division, change-order pricing with 500 bp/day rush capped at 3000 bp and 12000 bp rework, condition factors 6000/4000/2500 bp, posture thresholds 8000/10000 bp with boundary semantics); all `applies_to` endpoint scopes enumerated. 0 missing.
- **Contract 3 (§3 Path Purity):** 522 backticked tokens scanned in §3; 0 path-like tokens, 0 bare HTTP-method tokens, 0 method+path combinations. Endpoints referenced exclusively via state-transition framing, role + action verb, or capability description.

The file ends at the §5 error catalogue with no audit footer. The two forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-15T01:45:00.000Z

Both directories are populated and all modules import cleanly. Final summary:

## Summary

**Directories populated:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1916_scenic_shop_set_fabrication/test_helpers/` — 9 files (`__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1916_scenic_shop_set_fabrication/test_suite/` — `conftest.py` + 15 test files (`test_01_shop_and_clients.py` … `test_15_boundaries.py`)

**Test counts per queue:**
- **Queue A (Difficulty):** 56 tests emitted across all 27 instances; each instance has ≥2 tests (verified via `Design: Difficulty/<rule_id>/<instance.name>` tags).
- **Queue B (Corner):** 69 tests emitted across 56 non-stub instances; each has ≥1 test (`Design: Corner/<section>/<instance.name>` tag). Total: 125 test functions.

**Instances skipped:**
- 4 corner stubs excluded per their `excluded_because:` pointers (assertions owned by queue A):
  - `Corner/state_machines/corner_cascade_change_order_approval` → owned by `transitive_cascade/change_order_approval_cascade_releases_bays_and_recomputes_posture`
  - `Corner/state_machines/corner_cascade_bid_acceptance` → owned by `transitive_cascade/bid_acceptance_cascade_spawns_production_reviews_and_posture`
  - `Corner/state_machines/corner_cascade_strike_reclaim` → owned by `transitive_cascade/strike_reclaim_cascade_restores_stock_and_inventory_value`
  - `Corner/state_machines/corner_priority_state_before_safety` → owned by `priority_pair_validation_conflict/start_build_state_before_safety`
- No non-stub instances were skipped — all passed the PRD-first two-condition filter.

**Verification performed:**
- All 21 Python files parse cleanly via `ast.parse`.
- `test_helpers` imports without error; `ApiClient` exposes 71 endpoint methods (one per PRD §4 row).
- All 15 test modules import cleanly against the framework.
- Every test docstring ends with a single `Design: Difficulty/...` or `Design: Corner/...` line matching an existing instance `name:` in the source YAML.
- All monetary arithmetic assertions were hand-derived from PRD-pinned formulas (e.g., 1240800 for the DETAILED baseline, 662000 for the TIGHT+rush CO, 156000 for the rush-cap CO pair, 28768 for per-line rounding, 637560 vs 667920 for the tier boundary, 29375 for the strike reclaim cascade).

(Note: the subagent's first invocation halted after writing test_helpers/ + conftest.py; it was resumed via SendMessage and completed the full suite.)

## Step 6: Generate Implementation — 2026-08-15T01:40:00.000Z

Implementation complete and verified.

## Summary

**Files written** in `/home/ubuntu/github/CodingPRD/tasks/task_1916_scenic_shop_set_fabrication/workspace/implementation/`:

- `start.sh` — executable foreground launcher; guards `pip install` behind a `python3 -c "import flask"` check (no-op on per-test reboots), then `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000)
- `app.py` — Flask entry point, envelope-shaped error handlers (ApiError/404/405/500), per-request global lock, blueprint registration
- `core.py` — in-memory store (13 dicts, starts empty, zero seeding), logical clock (default `2026-08-01T00:00:00Z`), response envelope (`meta.api_request_id`/`api_request_timestamp` with 3 fractional digits, `response_type`, `data`, list pagination `limit`/`offset`/`total_count`/`has_more` in meta), auth (`X-User-ID`/`X-User-Role`, 7 roles), validation helpers, round-half-up Decimal math, all calculations (bid_price_detailed with pre-discount volume tier, bid_price_rom with 28-day urgency window, safety factors with load amplification before division, change_order_price with overtime/rush-cap/rework branches, capacity posture thresholds, stock valuation), and aggregate recomputation
- `routes_commercial.py` — shops, summary, run-epoch, clock, clients, design packages (supersession), takeoffs, takeoff lines (OCC, stock consume/restore), bids (full negotiation cycle + accept cascade)
- `routes_production.py` — productions (build gates, load-in, strike reclaim find-or-create, close barriers), engineering reviews (SoD, safety thresholds, ON_HOLD loop), finish samples, change orders (OCC, pinned pricing, 4-step approval cascade with per-step version bumps, bay auto-release), bay reservations (half-open overlap, soft delete), stock items (uniqueness, OCC adjust), transport plans (fleet overlap windows)
- `requirements.txt` — `flask>=2.2`

**Endpoint count: 65** — every route in the SCAFFOLD §1.5 endpoint table.

**Verification:** booted via `bash start.sh` on port 19166 and ran a ~70-assertion lifecycle smoke test (0 failures) covering: both pricing variants with hand-computed cent values (613674 DETAILED incl. per-line rounding + overhead/margin staging; 1400000 ROM), takeoff lock at submit, all three OCC 412s, supersession staleness at submit, negotiation round increments, accept cascade (production spawn, shop committed hours/ratio, client outstanding), engineering SoD 403 and 1.50/2.00 boundary passes, ON_HOLD loop, finish gates, bay overlap/adjacency/deadline 422/409s, fleet over-commit, load-in plan execution, strike reclaim find-or-create + DEPLETED↔ACTIVE flips, CO pricing (rework 12000 bp at LOADED_IN + rush 1500 bp), CO approval cascade with production version +4 and deadline-shift bay release, close barrier ordering, run-epoch bid expiry, summary shape, pagination validation, and auth 401/403s.

**Fresh-boot confirmation:** restarted the server via `start.sh` after the full run — `GET /scenic/clients` returned `total_count: 0` and the clock read the normative `2026-08-01T00:00:00Z` default; the full smoke suite then passed again on the fresh process. Storage is purely in-memory dicts, so every per-test-server relaunch starts from empty state.

## Step 7: Run Tests and Iterate — 2026-08-15T02:10:00.000Z

Verified independently: sweep 3 shows 125/125 passed, 0 failed in all 8 rounds. Exit condition met.

---

## Summary

**Iterations run:** 3 eight-round parallel sweeps
- Sweep 1: 117/125 in all 8 rounds (8 deterministic failures, identical across rounds)
- Sweep 2: 124/125 in all 8 rounds (1 deterministic failure)
- Sweep 3: **125/125 in all 8 rounds — clean exit**

**Tests deleted:** none. Every failing test traced to a verbatim PRD rule; all were repaired, none removed.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1916_scenic_shop_set_fabrication/test_helpers/assertions.py` — added `assert_instant_equals(actual, expected_iso)` (with private `_parse_instant`): compares ISO 8601 datetimes as instants, accepting both `Z` and `.000Z` renderings. Why: PRD pins three fractional digits only for `created_at`/`updated_at` (§2.5) and `api_request_timestamp` (§2.2); the string rendering of `built_at`/`load_in_deadline_at` is not uniquely derivable, so exact-string assertions on those fields collapsed the two-reader test while the underlying instant rules (clock reading recorded; deadline shifted by whole days; conservation on reject/withdraw) are PRD-covered and remain asserted at full strength (STEP 1c partial-coverage split, not a weakening).
- `/home/ubuntu/github/CodingPRD/tasks/task_1916_scenic_shop_set_fabrication/test_helpers/__init__.py` — exported `assert_instant_equals`.

**Fixes applied to `test_suite/` (the 8 sweep-1 failures + 1 sweep-2 failure, exact list):**
1. `test_03_bid_lifecycle.py::TestBidListFiltering::test_bid_list_combines_client_and_status_filters` — added missing `setup_shop` import (NameError; PRD §4 list-filter rule unchanged).
2. `test_03_bid_lifecycle.py::TestBidValidationErrors::test_get_nonexistent_bid_returns_404` — added missing `setup_shop` import (sweep 1) and missing `NON_EXISTENT_UUID` import (surfaced in sweep 2 after the first NameError was fixed; PRD §2.6 priority-3 rule unchanged).
3. `test_05_finish_samples.py::TestCompleteBuildGateOnSamples::test_complete_build_succeeds_after_sample_approved` — `built["built_at"] == "2026-08-01T00:00:00Z"` → `assert_instant_equals(...)`; server legitimately renders `.000Z`.
4. `test_06_change_orders.py::TestChangeOrderApprovalCascade::test_approval_applies_cascade_and_releases_late_bays` — `load_in_deadline_at == "2026-09-23T00:00:00Z"` → `assert_instant_equals(...)` (deadline −3 days cascade still asserted).
5. `test_06_change_orders.py::TestChangeOrderRejectConservation::test_reject_conserves_production_price_and_hours` — `load_in_deadline_at == "2026-09-26T00:00:00Z"` → `assert_instant_equals(...)` (reject-conservation still asserted).
6. `test_06_change_orders.py::TestChangeOrderWithdraw::test_withdraw_proposed_co_leaves_production_untouched` — same deadline assertion converted (withdraw-conservation still asserted).
7. `test_08_transport_and_load_in.py::TestLoadInBuffer::test_gap_exactly_two_days_passes` — `built["built_at"] == "2026-09-24T00:00:00Z"` → `assert_instant_equals(...)` (clock-reading rule still asserted).
8. `test_15_boundaries.py::TestSafetyFactorBoundaryNegative::test_sf_below_one_five_fails` — fixture numbers fixed: `member_capacity_lb` 5999 → 5979 at `design_load_lb` 4000. Why: PRD §3.4 pins round-half-up to two decimals *before* the 1.50 gate; 5999/4000 = 1.49975 rounds to exactly 1.50 and passes approval, so the old fixture could never produce the asserted `ERR_SAFETY_FACTOR_INSUFFICIENT` (test arithmetically contradicted the PRD sentence it cites). 5979/4000 = 1.49475 → rounds to 1.49 < 1.50, the largest failing integer at that load, preserving boundary intent.

**Fixes applied to `implementation/`:** none. The implementation was PRD-faithful on every failure — all 9 distinct failing tests were test-artifact bugs (2 missing imports, 5 non-uniquely-derivable string-format assertions, 1 rounding-arithmetic fixture error). No PRD-required check was touched, added, or weakened.

## Step 8: Finalize PRD — 2026-08-15T02:20:00.000Z

Task complete. `PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_1916_scenic_shop_set_fabrication/workspace/PRD_FINALIZED.md`.

## Line counts / delta
- `PRD.md`: 312 lines — `PRD_FINALIZED.md`: 314 lines — **+2 lines (+0.64%)**

## Changes (exactly one edit)
- **§2.5 Common Resource Properties — insert** — added a two-sentence rendering convention after the system-managed-fields bullet list: every datetime the server emits is rendered as ISO 8601 UTC with exactly three fractional digits and a trailing `Z` (e.g., `2026-08-01T00:00:00.000Z`), explicitly covering `created_at`/`updated_at`, `meta.api_request_timestamp`, the clock capability's `current_utc`, clock-recorded fields (`valid_until`, `built_at`), deadline fields (`load_in_deadline_at`), and echoed request datetimes (`load_in_at`, `strike_at`, `build_start_at`, `window_start`, `window_end`, `depart_at`, `arrive_at`) — impl: `core.py:80-82` (`iso()`), `core.py:136-146` (`pub()` serializes every datetime through `iso()`), `core.py:162` (`_meta`), `routes_commercial.py:130` (`current_utc`).

## Items from step_7_diff verified as NO-edit
- **Missing-import fixes (#1, #2):** pure test bugs (`setup_shop`, `NON_EXISTENT_UUID` NameErrors); no PRD silence.
- **Safety-factor boundary fixture (#8):** PRD §3.4 already pins round-half-up-to-two-decimals on `sf_static` before the gate ("each rounded half-up to two decimal places… a value of exactly 1.50 passes"), reinforced by §2.10. Impl confirms (`core.py:393-399` computes `rhu2(member_capacity/design_load)`; `routes_production.py:262` gates the stored rounded value against `Decimal("1.50")`). The old fixture (5999/4000 = 1.49975 → rounds to 1.50 → passes) arithmetically contradicted the PRD; pure fixture bug, PRD prose already unambiguous.

## Per-edit pre-edit search log (Edit 1, the only edit)
- **(a) Subject:** string rendering format of server-emitted datetime values.
- **(b) Impl paths enumerated:** `core.py:80-82` (`iso()` — sole formatter, always 3 fractional digits + `Z`); `core.py:136-146` (`pub()` — applies `iso()` to every `datetime` in any `data` payload, so all resource datetime fields); `core.py:159-163` (`_meta()` → `api_request_timestamp`); `core.py:166-183` (`ok`/`ok_list`/`error_response` — no serialization path bypasses `pub`/`_meta`); `routes_commercial.py:130` (clock endpoint `current_utc` via `iso()`); all datetime-storing fields: `created_at`/`updated_at` (`core.py:120-133`), package `load_in_at`/`strike_at` (`routes_commercial.py:189-210`), bid `build_start_at` (`routes_commercial.py:420`) and `valid_until` (`routes_commercial.py:476, 520, 561`), production `load_in_deadline_at`/`strike_at`/`build_start_at` copies (`routes_commercial.py:599-606`), `built_at` (`routes_production.py:85`), CO deadline shift (`routes_production.py:505-506`), reservation `window_start`/`window_end` (`routes_production.py:563-592`), plan `depart_at`/`arrive_at` (`routes_production.py:729-759`).
- **(c) Wording adjustment:** because `pub()`+`iso()` render *every* emitted datetime identically — not just the Step-7 fields `built_at`/`load_in_deadline_at` — the wording was scoped as a uniform convention over all response datetimes; a field-narrow patch would have falsely implied other fields render differently. Wording is restricted to emitted rendering only, saying nothing about input parsing (impl `parse_dt`, `core.py:89-101`, accepts offsets/naive strings), avoiding any narrowing of §1's interpretation rule. The existing §2.5 bullets and §2.2 prose were kept verbatim.

## Step 9: Complete PRD — 2026-08-15T02:32:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1916_scenic_shop_set_fabrication/workspace/PRD_COMPLETED.md` is written — a minimal inline patch over `PRD_FINALIZED.md`, aligned to `implementation/` (`core.py`, `routes_commercial.py`, `routes_production.py`, `app.py`).

**Size delta**: PRD_FINALIZED.md 314 lines / 52,457 chars → PRD_COMPLETED.md 314 lines / 55,421 chars (char-delta +2,964; 16 paragraphs revised in place, no lines added/removed, no new sections).

**Counts**: 18 ambiguity-pins, 3 mismatch-revisions (21 changes total).

**Changes** (section — insert/revise — kind — what — impl ref):

- §2.2 — insert — ambiguity — pinned that action endpoints return the resource named by the path (bid actions incl. accept return the bid; production lifecycle actions return the production; review/sample/change-order/transport-plan actions return those resources; run-epoch returns the updated shop) — routes_commercial.py:615, routes_commercial.py:117, routes_production.py:159/522
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` or `offset` rejected with `ERR_VALIDATION` (400); `created_at` ties broken by creation sequence — core.py:288-317, core.py:289
- §2.4 — insert — ambiguity — clock-set accepts any parseable instant, past or future, no range check — routes_commercial.py:123-130
- §2.5 — revise — ambiguity — `version` starts at 1 at creation — core.py:120-128
- §2.6 — revise — ambiguity — added `shop_id` to the tier-3 body-referenced identifier existence list — routes_commercial.py:146, routes_production.py:653
- §2.9 — revise — mismatch — removed the claim that a takeoff's pinned revision is compared at use; `pinned_package_revision` is informational only, never re-validated — no such check exists anywhere in impl
- §3.2 — insert — ambiguity — a takeoff may be opened against a package in any status (`CURRENT` or `SUPERSEDED`) — routes_commercial.py:252 (no status check)
- §3.2 — insert — ambiguity — stored line echoes the inapplicable conditional field as null (`stock_item_id` on PURCHASE, `unit_cost_cents` on STOCK) — routes_commercial.py:346-347
- §3.2 — revise — mismatch — unknown-field `ERR_VALIDATION` applies only to endpoints that consume a request body; body-less action endpoints ignore supplied fields; also added wrong-JSON-type and malformed/non-object body to the `ERR_VALIDATION` list — core.py:212-228, body-less endpoints e.g. routes_commercial.py:509/618, routes_production.py:252/370/492
- §3.2 — revise — ambiguity — `waste_pct_bp` defaults to 0 and must be at least 0 — routes_commercial.py:318-319
- §3.3 — insert — ambiguity — bid creation performs no client/package ownership-consistency check and does not require the package to be `CURRENT`; staleness bites only at submit/accept — routes_commercial.py:427-433
- §3.3 — revise — ambiguity — `valid_until` is null at creation and stays null until first submission — routes_commercial.py:476
- §3.3 — insert — ambiguity — submitting a DETAILED bid whose takeoff is already `LOCKED` succeeds; the lock is idempotent — routes_commercial.py:523-527
- §3.3 — revise — ambiguity — `counter_price_cents` (any integer) and `note` are type-validated but not persisted on the bid — routes_commercial.py:540-545
- §3.3 — revise — ambiguity — `revised_price_cents` may be any integer, no positivity constraint — routes_commercial.py:558-559
- §3.4 — revise — ambiguity — review resubmit retains the recorded `revision_note` — routes_production.py:313-321
- §3.4 — revise — ambiguity — finish-sample resubmit retains the recorded `rejection_note` — routes_production.py:414-417
- §3.6 — revise — ambiguity — bay-overlap check is scoped to `ACTIVE` reservations on the same `bay_slot` of the same shop — routes_production.py:574-583
- §3.7 — revise — ambiguity — strike reclaim lines require `quantity` > 0 and `replacement_cost_cents` > 0 (`ERR_VALIDATION`) — routes_production.py:133-136
- §3.7 — insert — ambiguity — an existing matched stock item keeps its own `replacement_cost_cents` (line's cost used only at creation); a strike-minted item records the addition as a mutation so its `version` is 2 after its first reclaim line — routes_production.py:139-155
- §3.7 — revise — mismatch — close recomputes shop capacity but removes nothing itself, since the production already left the committed set when it exited `IN_BUILD`/`ON_HOLD` (was previously worded as "subtracts its committed_crew_hours … at close") — routes_production.py:177-180, core.py:328-348, core.py:50

**Notable non-changes verified against impl**: full validation-cascade ordering (§2.6) matches impl check order at every endpoint; detailed/ROM/change-order pricing formulas and rounding steps match exactly; ROM "discarding any fractional day" was left as-is because `timedelta.days` floor differs from truncation only for negative spans, which can never cross the 28-day urgency boundary — behaviorally identical.
