# Worklog — task_2244_heavy_equipment_auction_global_bidding

## Step 1: Create task directory — 2026-09-01T11:00:00.000Z

Created `tasks/task_2244_heavy_equipment_auction_global_bidding/` and `tasks/task_2244_heavy_equipment_auction_global_bidding/workspace/` (directory name pre-allocated by the invoker; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T12:36:05.000Z

All three scaffold artifacts are complete and lint-clean.

**Files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2244_heavy_equipment_auction_global_bidding/`)
- `SCAFFOLD.yaml` — 3,882 lines, §1.0–§1.7 only (no design keys), scenario text verbatim, `domain_name: heavy-equipment-auction`, `api_prefix: "/"`, `difficulty_level: beyond_expert`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2,534 lines, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 6,226 lines, single key `scaffold_corner_design`

**SCAFFOLD counts**
- 17 entities, 11 state machines (Lot and Invoice each carry two independent axes; Sale and RefurbishmentOrder cyclic; Consignment compound/bubble-up), 2 OCC concurrency rules
- 7 calculations, 41 priority-ordered validations, 87 endpoints, 63 error codes, 7 roles (all with `identity:`; `Consignor` and `Bidder` entity-backed)
- Complexity profile: `pricing_engine` × `compliance_audit`, layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; `role_model: segregation_of_duties`; `consistency_model: immediate`

**§1.8 difficulty design — 21 instances** across all 9 required rule_ids: 2 dual_variant_calc, 3 combinatorial_formula, 2 non_linear_state_machine, 2 transitive_cascade, 2 priority_pair_validation_conflict, 3 boundary_precision_check, 3 cross_entity_state_dependency, 2 resource_temporal_overlap, 2 compensating_invariant.

**§1.9 corner design — 82 instances** (57 with full `test_recipe`, 25 `excluded_because:` stubs) over the nine claim-extraction-guide sections: entities 11, state_machines 16, calculations 13, validations 14, endpoints 6, errors 12, RBAC 4, cross-cutting complexity layers 5, consistency model 1.

**Verification**
- All 103 instance names unique across the two design files; every stub cites an existing §1.8 instance name and carries no `test_recipe`
- All 63 catalogued error ids are reachable from at least one design instance (0 unmentioned)
- No forbidden concurrency vocabulary; logical clock pinned to `2026-08-01T00:00:00Z` in every setup

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(Coverage line from the same run: 87 endpoints, 17 entities, 21 §1.8 instances, 57 §1.9 instances, 1,426 calls scanned.)

## Step 3: Copy shared files — 2026-09-01T12:36:05.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-01T12:52:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2244_heavy_equipment_auction_global_bidding/workspace/PRD.md`.

**Size:** 557 lines, ~15,270 words.

**Sections covered**
- §1 Introduction — 3 paragraphs from the scaffold `scenario`, plus the two framing commitments (integer-cent money, custody/obligation on separate axes).
- §2 Global Specifications — 10 subsections: RBAC (7 roles, `X-User-ID`/`X-User-Role`, entity-backed vs opaque identity, ownership surface); §2.2 pasted verbatim from `section-2.2-response-structure.md`; pagination + every list filter; flat topology and the path-then-body identifier resolution order with all 17 path-id → 404 mappings; common fields, the `Bid`/`Payment` `common_fields: false` exception, and the logical clock (default `2026-08-01T00:00:00Z`); cents/rounding discipline including per-tier rounding steps and the storage-day floor; OCC on `expected_sale_version` / `expected_invoice_version`; the full 41-step rejection ladder; derived counters, cascades and the two parallel-axis entities; sanctions, default strikes, segregation of duties, deposit conservation identity.
- §3 Business Logic — 9 narrative subsections (intake; inspection/grading/refurb/publication; compliance desk; scheduling and catalogue; bidder admission; the ring; reserve/negotiation loop; buyer settlement; load-out, seller settlement and abandonment). All 7 calculations are written as business prose with normative order-of-operations, all 65 transitions across 11 machines, and all cascade depths.
- §4 Endpoint Definitions — 87 rows, exactly 4 columns, generated mechanically from the scaffold; preamble states the 17 `201 Created` operations vs `200 OK`.
- §5 Error Handling — 63 rows, exactly 2 columns. Document ends here with no audit footer.

**Coverage audit — all three Hard Contracts PASS**
- Contract 1 (Field-Name Coverage): 171/171 required backticked names present (146 entity fields ∪ endpoint inputs ∪ 18 path params ∪ output-shape members); 0 missing, verified on two passes.
- Contract 2 (Rule Coverage): 63/63 error IDs in §1–§3 prose (not merely the §5 table); 41/41 validation priorities as an ordered ladder in §2.8; 65/65 transitions and all 55 state tokens; 7/7 calculations with every constant traceable in prose; 2/2 concurrency rules with both OCC field names and 412 errors.
- Contract 3 (§3 Path Purity): 0 URL paths and 0 HTTP method tokens in §3, backticked or raw.

**Two notes worth relaying**
1. The scaffold's `validations` and `errors` refer to an `X-Role` header; SKILL.md fixes the contract headers as `X-User-ID`/`X-User-Role`, so the PRD uses `X-User-Role`. If the hidden test suite was generated from the scaffold's wording, that header name will mismatch.
2. Stale `/tmp/t4.md`, `/tmp/t5.md` and `/tmp/required_names.json` from a *different* task (a `convention-center` domain) were present in `/tmp` and would have been silently pasted in had they been trusted. I regenerated all three from task 2244's own `SCAFFOLD.yaml`. Any parallel doc-generation runs sharing `/tmp` should use task-scoped filenames.

`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml` and all sibling task directories were never read.

## Step 5: Generate unit tests — 2026-09-01T14:44:00.000Z

Generation is complete. Final state of the deliverable:

## Files written

**Stage 1 — `/home/ubuntu/github/CodingPRD/tasks/task_2244_heavy_equipment_auction_global_bidding/test_helpers/`**
`__init__.py`, `api_client.py` (88 endpoints), `api_errors.py` (63 ids + status map), `constants.py`, `types.py`, `test_users.py` (7 roles + second-identity users), `factories.py` (~45 payload builders), `fixtures.py` (~35 composite fixtures, tiered from `new_yard` up to `settled_then_defaulted_invoice`), `assertions.py`.

**Stage 2 — `.../test_suite/`** — `conftest.py` plus 14 test modules, 100 tests total (5,771 lines):

| file | tests | file | tests |
|---|---|---|---|
| test_01_yards_bays_and_reference_data | 7 | test_08_hammer_close_and_reserve | 6 |
| test_02_consignment_and_lot_intake | 9 | test_09_consignor_negotiation | 5 |
| test_03_inspection_and_grading | 10 | test_10_invoice_pricing | 7 |
| test_04_title_and_export_documentation | 6 | test_11_storage_payment_and_release | 9 |
| test_05_auction_scheduling_and_catalogue | 7 | test_12_loadout_scheduling | 6 |
| test_06_bidder_admission_and_deposits | 9 | test_13_settlement_and_abandonment | 7 |
| test_07_ring_bidding_and_caps | 6 | test_14_access_control_and_error_catalogue | 6 |

## Translation counts

- **Queue A (difficulty, §1.8):** 21 instances / 9 rule groups; 20 translated → **40 tests** (exactly 2 per instance).
- **Queue B (corner, §1.9):** 82 instances, 25 of which are `excluded_because` stubs; all **57 non-stub instances translated → 60 tests** (three instances earned a second test).
- Audit results: 100 tests, 77 distinct `Design:` tags, every tag resolves to a real instance, exactly one tag per test, **zero stubs translated**, no `skip`/`skipif`/`xfail` anywhere, all 275 PRD citations verified as literal substrings of `workspace/PRD.md`, all modules import and byte-compile.

## Instance skipped (gap left as a gap)

`Difficulty/dual_variant_calc/bid_cap_forecast_versus_chronological_replay` — PRD §3.5 describes the exposure read's fields but never names the two `variant` literals the recipe sends, so a PRD-only reader cannot construct the request (condition 2 of the two-condition filter fails). No placeholder, xfail or weakened test was emitted. Exposure-dependent *corner* instances were still translated by asserting through `registration.bid_cap_cents` and `bidder.open_exposure_cents`, which the PRD does specify.

## Surface-conflict rulings (PRD wins)

- Headers are `X-User-ID` / `X-User-Role` (not the scaffold's `X-Role`).
- `ERR_SLOT_OUTSIDE_DEADLINE` asserted at **422** (PRD §5 table) against the corner recipe's 409.
- Overlapping rebooking asserted as 409 `ERR_SLOT_OVERLAP`: PRD §3.9 scopes the superseded-slot exception to "the tonnage sum" only, so the difficulty instance's "excluding superseded" aspect was translated via a non-overlapping rebooking (bay reserves 36,000 kg, not 72,000).
- Field/enum spellings taken from the PRD: `settlement_variant`, integer `bay_number`, bid status `ACTIVE`, `gross_hammer_cents` over CONFIRMED/SETTLED only.
- Fee waivers act as a second settlement officer (`SECOND_SETTLEMENT`) because the credit approver is blocked by §2.10 segregation of duties.

## Step 6: Generate implementation — 2026-09-01T15:22:00.000Z

Note (orchestrator): Steps 5 and 6 ran sequentially rather than concurrently, so `test_suite/` and `test_helpers/` already existed on disk when the impl-gen subagent started. Physical isolation was replaced by an explicit hard constraint in the subagent prompt forbidding any read/ls/glob/grep of those two directories; the subagent confirmed it generated purely from PRD.md + SCAFFOLD.yaml + INSTRUCTION.md.

The implementation is complete and verified.

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_2244_heavy_equipment_auction_global_bidding/workspace/implementation/` (21 files, ~3,930 lines):

**Launcher / infrastructure**
- `start.sh` — `set -euo pipefail`, `cd $(dirname $0)`, guarded install (`if ! python3 -c "import flask"`), `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000). The install guard is deliberate: an unconditional `pip install` on every per-test reboot causes boot contention.
- `requirements.txt` — `flask>=2.0`
- `app.py` — app factory, 7 blueprints, `ApiError`/`HTTPException`/catch-all handlers emitting the error envelope, a global `RLock` acquired in `before_request` and released in `teardown_request`.

**Core**
- `db.py` — in-memory `Store` over 17 dicts, logical clock (default `2026-08-01T00:00:00Z`), wall clock for `created_at`/`updated_at`, hidden `_seq` for stable ordering. Nothing is ever seeded.
- `response.py` — envelope helpers (`req_` ids, ISO-8601 with exactly 3 fractional digits, `_`-prefixed keys stripped, Decimal→float).
- `errors.py` — all 63 error IDs → HTTP status.
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (PRD wins over the scaffold's `X-Role`), `@endpoint(*roles)`, ownership check, typed field/query validators, pagination (10/1/100/0).

**Domain services**
- `services/constants.py`, `money.py` (Decimal + ROUND_HALF_UP), `calculations.py` (all 7 calculations), `derive.py` (rollups, deposit waterfall, invoice stamping, knock-down, auction close, settlement post/reverse, the 4-depth abandonment cascade).

**Routes** — `reference.py` (14), `intake.py` (14), `inspection.py` (9), `auctions.py` (8), `bidding.py` (13), `sales.py` (8), `settlement.py` (22).

## Endpoint coverage

**87/87 — exact match.** I parsed the PRD §4 table and diffed method+path against the registered Flask url_map: zero missing, zero extra.

## Entity field audit

Parsed the 17 entity field lists out of `SCAFFOLD.yaml` and diffed them against live instances of every entity created through the API: **0 entities with any missing or extra field**.

## Boot verification

`PORT=18999 bash start.sh` → HTTP-ready after ~1s; `GET /yards` and `GET /invoices` return empty paginated envelopes (confirming no seeded data); unauthenticated request returns `ERR_UNAUTHENTICATED` 401; process killed cleanly. Also confirmed no `open(`/sqlite/pickle/`/tmp` usage anywhere — storage is dicts only.

## Functional smoke testing

Three end-to-end runs against fresh servers covering: full domestic happy path (intake → lien → grading → catalogue → ring → hammer → invoice → payment → release → load-out → settlement → reconcile); cross-border negotiation path (reserve miss → counteroffer → accept, DE tax, financing fee, finalisation with storage accrual, export packet reject/reopen/clear, partial payment, rebooking); and an unreserved/`LOW_VALUE_FLAT`/`TIMED_ONLINE` path plus abandonment with settlement reversal, bay-capacity aggregation, slot overlap, no-show, and replacement-lot creation. Every hand-checked money figure matched the PRD arithmetic (marginal premium tiers, 10%-with-50,000-floor flat schedule, 19% DE tax on subtotal only, 25%-of-hammer storage cap, deficiency claim, commission floors, deposit waterfall across sibling invoices). Deposit conservation (`total = held + available + forfeited`) asserted and held after forfeiture.

Four apparent smoke "failures" were all my test's wrong expectations, each re-checked against PRD §2.8/§5 and the implementation confirmed correct: `ERR_INVOICE_NOT_PAID`, `ERR_SLOT_NOT_IN_WINDOW` and `ERR_BAY_CAPACITY_EXCEEDED` are 409 (not 422); an unknown `X-User-Role` is `ERR_UNAUTHENTICATED` 401 per rung 1; and a replayed settlement hits rung-8 `ERR_INVALID_STATE` before rung-17 `ERR_DUPLICATE_SETTLEMENT` because the first posting already moved the sale to `SETTLED`.

**Notable spec decisions** (each traced to PRD text): validation follows the §2.8 ladder ordering wherever it disagrees with §3 narrative ordering (e.g. bay capacity at rung 31 before slot overlap/deadline at rung 33); the superseded-slot exclusion applies to the tonnage sum only, not the overlap check, per §3.9's explicit wording; conditionally-required transition fields (`correction_note`, `qa_note`, `rejection_reason`, …) are preconditions returning `ERR_INVALID_STATE` since the endpoints declare them optional; abandonment leaves the lot in `HAMMERED` when no settlement was ever posted.

## Step 7: Run tests and iterate — 2026-09-01T15:44:00.000Z

All 8 parallel rounds now report 100/100 passed, zero failures, zero flakiness.

## Summary

**Iterations run:** 3 sweeps (8 parallel rounds each). Sweep 1: 92/100 in all rounds. Sweep 2 (after 8-item fix batch): 99/100 in all rounds. Sweep 3: **100/100 in all 8 rounds**.

**Assertions deleted (PRD-silence / PRD-contradiction, STEP 1c partial-coverage splits — the rest of each test kept):**
- `test_suite/test_01_yards_bays_and_reference_data.py` (`test_yard_creation_returns_the_stored_record_in_the_object_envelope`): dropped `assert yard["created_at"].startswith("2026-08-01T00:00:00")`. COMPUTED/DEFAULT SILENCE — PRD §2.5 exhaustively names the clock-stamped timestamps as "`placed_at` on a bid, `received_at` on a payment, and `hammered_at` on a sale"; `created_at` is never said to read the logical clock. Scaffold rule: `Corner/entities/yard_creation_returns_persisted_record_with_envelope`.
- `test_suite/test_06_bidder_admission_and_deposits.py` (`test_paddles_are_minted_by_the_server_starting_at_one_hundred_and_one`): dropped `assert first["created_at"].startswith("2026-08-01T00:00:00")`. Same PRD-silence category.
- `test_suite/test_13_settlement_and_abandonment.py` (`test_the_same_call_reverses_the_sellers_settlement_and_requeues_the_machine`): dropped the `consignor["lifetime_net_proceeds_cents"] == -25_000` assertion. PRD §2.9 defines the counter verbatim as summing "`net_proceeds_cents` across that consignor's settlements whose `status` is `POSTED`"; after reversal the row is `REVERSED`, so the PRD-faithful recompute yields 0. §3.9 only says the counter "is recomputed" — it never states the post-reversal value, so the expected -25,000 contradicts the verbatim counter definition. Scaffold rule: `Difficulty/transitive_cascade/abandonment_cascades_invoice_sale_settlement_lot_consignment`.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py::settled_then_defaulted_invoice` — re-reads `stage["lot"]` after posting the consignor settlement, because PRD §3.9 says posting "moves the sale `CONFIRMED → SETTLED` and the lot `HAMMERED → SETTLED`"; the stale staged copy still read `HAMMERED`.

**Fixes applied to `workspace/implementation/`:**
- `routes/reference.py::set_clock` — echoes the supplied `current_utc` string as given (PRD §2.5: the capability "accepts a single `current_utc` instant and echoes back `{ current_utc }`"); it previously re-formatted to 3-fractional-digit form, which is the §2.5 rule for resource timestamps, and this call "mutates no entity".
- `routes/inspection.py::create_condition_report` — moved the duplicate-report guard ahead of the lot-`INTAKE` state guard (PRD §3.2 "a replay is refused with `ERR_DUPLICATE_CONDITION_REPORT`"; ladder rung 17 "Replaying a create that already produced a row is a conflict, not a second row"), since the first filing moves the lot to `INSPECTED` and the generic guard would otherwise mask the named error.
- `routes/sales.py::create_consignor_settlement` — moved the `POSTED`-settlement duplicate guard ahead of the sale-`CONFIRMED` guard, for the same reason (PRD §3.9 / rung 17); posting moves the sale to `SETTLED`.
- `routes/auctions.py` (catalogue assignment) — moved the "lot already assigned to another auction" → `ERR_LOT_AUCTION_MISMATCH` check ahead of the lot-`CATALOG_READY` guard (PRD §3.4 rung 23); an already-assigned lot has left `CATALOG_READY`, so the named error was unreachable.
- `routes/settlement.py::create_payment` — restamps the registration's `bid_cap_cents` via `recompute_registration_cap` after a payment writes the invoice (PRD §3.5: "This forecast is restamped on the registration whenever any invoice of the registration is written, so `bid_cap_cents` tracks the money actually owed").

Storage remains in-memory only; no seeding, no endpoints/fields/side effects added beyond the cited PRD sentences. Transient `results.*.json` / `round.*.log` artifacts were removed from `workspace/implementation/`.

Orchestrator addendum: because the Step 7 subagent deleted the transient `results.*.json`, the orchestrator re-ran one final identical 8-round parallel sweep to restore the required artifacts. Result: `results.1.json` … `results.8.json`, **100/100 passed in every one of the 8 rounds**, zero flakiness.

## Step 8: Finalize PRD — 2026-09-01T15:51:00.000Z

Done. `PRD_FINALIZED.md` written.

## Line counts
- `PRD.md`: 557 lines / 126,967 bytes
- `PRD_FINALIZED.md`: 557 lines / 128,600 bytes
- Delta: **0.0% lines** (7 lines revised in place), **+1.29% bytes**

## Changes (one per bullet)
- **§2.5 (common resource properties)** — insert — `created_at`/`updated_at` are stamped from the server's real time of day, not from the logical clock, so setting the clock does not change what a later write stamps — `implementation/db.py:48,64-67,76`
- **§2.5 (logical clock)** — revise — the clock-set capability echoes `current_utc` back verbatim as supplied, not reformatted to the three-fractional-digit resource-timestamp shape — `implementation/routes/reference.py:21-29`
- **§2.8 rung 8** — revise — named three deliberate exceptions evaluated ahead of the generic `ERR_INVALID_STATE` guard (rung 17's duplicate condition report and duplicate settlement; rung 23's already-assigned limb, on catalogue assignment only) — `implementation/routes/inspection.py:56-67`, `routes/sales.py:190-197`, `routes/auctions.py:145-158`
- **§3.2 (condition report)** — revise — the duplicate-report check precedes both the lot-`INTAKE` and consignment-status guards — `implementation/routes/inspection.py:56-67`
- **§3.4 (catalogue assignment)** — insert — a lot already pointing at another auction is refused `ERR_LOT_AUCTION_MISMATCH` before any state guard — `implementation/routes/auctions.py:145-158`
- **§3.8 (payments)** — insert — a payment also restamps the registration's `bid_cap_cents` (per §3.5) — `implementation/routes/settlement.py:262-266`
- **§3.9 (consignor settlement)** — revise — the `POSTED`-duplicate check precedes the sale-`CONFIRMED` guard — `implementation/routes/sales.py:190-197`

**No edit made** for two `<step_7_diff>` items, deliberately:
- `lifetime_net_proceeds_cents` after reversal — `derive.py:recompute_consignor` (74-88) sums **POSTED** settlements only, so post-reversal it is 0, exactly what §2.9's verbatim definition yields. PRD already determines it; the deleted `-25_000` assertion was the wrong side.
- `test_helpers/fixtures.py` stale `stage["lot"]` — pure fixture bug; `derive.py:post_settlement` (481-486) already moves the lot `HAMMERED → SETTLED` as §3.9 states.

## Per-edit pre-edit search log

**A. §2.5 created_at**
(a) Subject: source of `created_at` / `updated_at` timestamps.
(b) Enumerated: `db.py:new_entity` (only writer of `created_at`), `db.py:touch` (only writer of `updated_at`), `db.wall` vs `db.now`; grepped `created_at|updated_at|db.wall|db.now()` repo-wide — every logical-clock read is a domain field (`placed_at`, `received_at`, `hammered_at`, storage/due/window comparisons), never `created_at`; `db.ordered`/`_waterfall_key`/`close_auction` use `created_at` only as a sort key with `_seq` tiebreak; `response.utc_stamp` (envelope) also real time.
(c) Adjustment: scoped the sentence to `created_at`/`updated_at` only and phrased the clock relation as "does not change what a subsequent write stamps", avoiding any claim about the sort-key or envelope semantics.

**B. §2.5 clock echo**
(a) Subject: response body of `POST /_clock/set_current_utc`.
(b) Enumerated: `routes/reference.py:set_clock` (sole handler), `middleware.field_dt`/`parse_iso` (rejects non-strings, so the echo is always the supplied string), `db.current_utc` (stores the parsed, offset-normalised datetime), `response.fmt_dt` (used for stored timestamps elsewhere, and as the dead fallback branch).
(c) Adjustment: said "the accepted instant exactly as the caller supplied it" and explicitly contrasted it with stored-resource formatting, so the three-digit rule in the same paragraph is not weakened for any other field; said nothing about what the clock *stores*, since a supplied offset is normalised internally.

**C. §2.8 rung 8**
(a) Subject: global position of the generic state guard relative to named conflicts.
(b) Enumerated all `ERR_DUPLICATE_*` and `ERR_LOT_AUCTION_MISMATCH` sites: `inspection.py:62` (before state), `sales.py:195` (before state), `bidding.py:162` (duplicate registration — no generic state guard on that endpoint, so unordered), `intake.py:165` (duplicate serial — before nothing state-bearing), `auctions.py:150` (assignment, before state) and `:174,176` (later, unreachable duplicates), `intake.py:335` (hammer — mismatch fires **after** the lot-`ASSIGNED` guard). Also re-checked rungs 18/19 ordering in `bidding.py:157-175` (duplicate → embargo → strikes → deposits, matching the ladder).
(c) Adjustment: limited the exception list to exactly three and scoped rung 23's limb with "on catalogue assignment only", so the hammer path (`intake.py:326-339`, state guard first) and the duplicate-registration/duplicate-serial paths are not mis-described.

**D. §3.2 condition report**
(a) Subject: guard order in condition-report creation.
(b) Enumerated: `inspection.py:create_condition_report:54-67`; also `rescore` (126) and `publish` (158-168) to confirm no duplicate guard exists there, and `assign_lot`'s report lookup (`auctions.py:139-158`) which assumes at most one report per lot.
(c) Adjustment: kept both state conditions verbatim and only moved the duplicate clause to the front; did not say "at most one report may ever exist", which would over-claim beyond the create path.

**E. §3.4 catalogue assignment**
(a) Subject: position of the already-assigned check within the eight-condition gate.
(b) Enumerated: `auctions.py:assign_lot:135-192` in full (early check at 149; consignment-accepted limb still at 173; second, dead duplicate at 175), plus `intake.py:hammer_lot:326-341` (the other `ERR_LOT_AUCTION_MISMATCH` producer) and `recompute_auction` (`derive.py:121-133`) for the `assigned_lot_count` side effect.
(c) Adjustment: named only the `auction_id`-already-set-elsewhere limb, not the "consignment accepted at intake" limb (which impl still evaluates late, after `ERR_CONSIGNMENT_NOT_CATALOGED`), and left the rest of the gate paragraph untouched.

**F. §3.8 payments**
(a) Subject: which derived fields a payment restamps.
(b) Enumerated every invoice-writing path and its registration handling: `create_invoice_for_sale`→`stamp_invoice`→`refresh_registration_money` (derive.py:303-306), `finalize_invoice` (settlement.py:105), `fee_waiver` (133), `abandon_invoice` (derive.py:592), `create_payment` (settlement.py:265 — cap only, not the deposit waterfall), versus `authorize_release` (162) and `default_invoice` (177-179) which write the invoice but do **not** restamp the cap. Also `recompute_registration_cap` (derive.py:161-169) with its SUSPENDED / null-leverage short-circuits, and the fact that no path calls `touch()` on the registration for a derived restamp.
(c) Adjustment: kept the insert local to the payments sentence rather than strengthening §3.5's already-universal "whenever any invoice … is written" claim (the default path would contradict a strengthened version); wrote "restamped as §3.5 requires" instead of restating the forecast formula, so the SUSPENDED short-circuit is not contradicted; and said nothing about the registration's `version`, since impl does not bump it here.

**G. §3.9 consignor settlement**
(a) Subject: guard order in consignor-settlement posting.
(b) Enumerated: `sales.py:create_consignor_settlement:186-199`, `derive.py:post_settlement:432-496` (moves sale `CONFIRMED → SETTLED`, hence the masking), `reverse_settlement:499-507` and `abandon_invoice:577-584` (a `REVERSED` row does not block a re-post), `auctions.py:reconcile_auction:230-240` (also filters settlements on `status == "POSTED"`).
(c) Adjustment: phrased the guard as "no `POSTED` settlement exists" (not "no settlement row exists"), so a reversed row leaving the sale re-postable stays consistent with `abandon_invoice`/`reconcile_auction`.

## Step 9: Complete PRD — 2026-09-01T16:14:47.000Z

Done. Both files verified at 557 lines with no structural change (every diff hunk is a one-line-for-one-line in-paragraph replacement; no new sections, no new paragraphs).

## Step 9 exit summary

**Source vs output:** `PRD_FINALIZED.md` 557 lines / 128,204 bytes → `PRD_COMPLETED.md` 557 lines / 144,582 bytes (**+16,378 bytes**, 44 lines revised in place).

**Counts:** 29 ambiguity-pins, 15 mismatch-revisions.

### Changes

- §2.3 Pagination — insert — ambiguity — empty `limit`/`offset` counts as absent; non-numeric is 400 — `middleware.py:265`
- §2.3 Pagination — insert — ambiguity — list ordering ties broken by insertion sequence — `db.py:81`
- §2.3 Filters — revise — mismatch — added `lifecycle_status` on a consignment's lots; empty filter = absent; non-member enum → 400; unknown params ignored — `routes/intake.py:123`, `middleware.py:290`
- §2.5 Common properties — revise — mismatch — `version` does *not* increment on derived-only restamps — `db.py:73`
- §2.6 Rounding — insert — ambiguity — decimals emitted as JSON numbers, trailing zeros not preserved — `response.py:37`
- §2.8 rung 3 — revise — mismatch — discriminator-conditional required fields report `ERR_INVALID_STATE` (409) after the state guard, not 400; `tonnage_kg` upper bound deferred past FK resolution — `routes/inspection.py:265`, `routes/settlement.py:406`
- §2.8 rung 8 — insert — ambiguity — closed list of the 15 unnamed §3 preconditions that resolve to `ERR_INVALID_STATE` — `routes/intake.py:76`, `routes/auctions.py:158,203,205`, `routes/settlement.py:149,238,414,543`
- §2.9 Derived counters — revise — mismatch — recomputation is not a versioned mutation; enumerated silent counters; bidder deposit-move exception (not forfeiture) — `services/derive.py:55,112,161`, `routes/bidding.py:22`
- §3.1 Yard — revise — mismatch — `code` uniqueness is not machine-enforced — `routes/reference.py:37`
- §3.1 Bay — revise — mismatch — `bay_number` uniqueness within yard is not machine-enforced — `routes/reference.py:101`
- §3.1 Consignor — revise — ambiguity — `unreserved_policy_ack` accepted in the create payload — `routes/reference.py:147`
- §3.1 Lot edit — insert — ambiguity — key-presence semantics, only `reserve_price_cents` nullable, not ownership-scoped — `routes/intake.py:224`
- §3.2 Rescore — revise — mismatch — also accepts `observed_hour_meter_reading`/`hour_meter_photo_ref`, restamps `hour_meter_variance_pct`, null rules — `routes/inspection.py:106`
- §3.2 Refurb order create — insert — ambiguity — no lot-state precondition — `routes/inspection.py:193`
- §3.2 `START`/`QA_PASS` — revise — mismatch — `INSPECTED` binds only the `DRAFT` leg; optional `qa_note` recorded; SoD vacuous with no report — `routes/inspection.py:253,277`
- §3.3 Export packet create — insert — ambiguity — no invoice-state gate; several packets may coexist — `routes/settlement.py:286`
- §3.4 Window conflict — revise — ambiguity — buffer extends the candidate at **both** ends against others' raw windows — `routes/auctions.py:24`
- §3.4 Assignment guards — revise — mismatch — published-report guard is a rung-8 `ERR_INVALID_STATE` evaluated before consignment/title; explicit null reserve clears — `routes/auctions.py:157,179`
- §3.4 Assignment result — insert — ambiguity — the 201 body is the updated lot — `routes/auctions.py:192`
- §3.5 Deposits — revise — ambiguity — `amount_cents` ≥ 1 with no ceiling, mandatory `reference`, returns the bidder — `routes/bidding.py:87`
- §3.5 Registration create — insert — ambiguity — paddle counts all prior statuses; no auction-status gate — `routes/bidding.py:230`
- §3.5 Credit decision — revise — mismatch — `REQUESTED`/embargo/strike screens bind `DECLINE` too; omitted credit limit = 0 — `routes/bidding.py:252`
- §3.5 Cancellation — insert — ambiguity — also zeroes `bid_cap_cents` — `routes/bidding.py:297`
- §3.5 Exposure read — revise — ambiguity — mandatory `auction_id`/`variant` query params, `REGISTRATION_FORECAST`/`LIVE_CHRONOLOGICAL`, registration-selection rule, not ownership-scoped, live `exposure_cents` = consumed hammer, `breached_at_sale_id` null for forecast — `routes/bidding.py:107`
- §3.6 Bid guards — insert — ambiguity — lot with null `auction_id` → `ERR_AUCTION_NOT_OPEN`; registration's own `auction_id` never cross-checked — `routes/bidding.py:326`
- §3.6 Live cap — insert — ambiguity — third tie-break by insertion order; only `NO_SALE` skipped — `services/calculations.py` (`live_chronological_cap`)
- §3.6 Hammer — revise — mismatch — mismatch guard fires only for an `ASSIGNED` lot with no `auction_id`; sits between state and open checks — `routes/intake.py:335`
- §3.6 Close cascade — insert — ambiguity — confirmation + invoice stamped inside each per-lot knock-down — `services/derive.py:375,414`
- §3.7 Counter-response — insert — ambiguity — over-cap `ACCEPT` → `ERR_BID_CAP_EXCEEDED` — `routes/sales.py:127`
- §3.8 Finalisation — insert — ambiguity — no money/custody precondition; replay → `ERR_INVALID_STATE`; regression only from `PAID` — `routes/settlement.py:100`
- §3.8 Settlement preview — revise — ambiguity — mandatory `variant` query param (`PROVISIONAL`/`FINAL`), exactly 15 fields — `routes/settlement.py:66`
- §3.8 Fee waiver — revise — ambiguity — `waiver_cents` ≥ 0; no state precondition; SoD outranks the ceiling and is vacuous when the approver is null — `routes/settlement.py:117`
- §3.8 Payments — insert — mismatch — refusals reached in ladder order (state → overpayment → currency), not the prose order — `routes/settlement.py:237`
- §3.8 Money axis — insert — ambiguity — deposit-covered invoice stays `UNPAID` at zero outstanding and cannot be paid — `routes/settlement.py:239`
- §3.8 Release authorisation — revise — mismatch — evaluation order is custody → sale → title → payment → export, so title outranks payment; sale guard is `ERR_INVALID_STATE` — `routes/settlement.py:146`
- §3.9 Slot booking payload — insert — ambiguity — explicit-null `tonnage_kg` defaults to weight; upper bound checked after FK resolution but still 400 — `routes/settlement.py:391,406`
- §3.9 Slot constraints — revise — mismatch — crane rating evaluated before both interval rules; superseded slot excluded from tonnage but not from overlap — `routes/settlement.py:443,452`
- §3.9 Completion — revise — ambiguity — requires invoice `LOADOUT_BOOKED`; lot moves only from `SETTLED` — `routes/settlement.py:535`
- §3.9 Cancellation — insert — ambiguity — Bidder `NO_SHOW` / checked-in cancel → `ERR_ROLE_NOT_PERMITTED` after ownership; `cancel_reason` written only when supplied — `routes/settlement.py:574`
- §3.9 Seller settlement — insert — ambiguity — returns 201; lot move conditional on `HAMMERED` — `services/derive.py:484`
- §3.9 Abandonment depth 1 — revise — ambiguity — `chargeable_storage_days` restamped; cancelled slots get `cancel_reason` `ABANDONED` — `services/derive.py:527,547`
- §3.9 Abandonment depth 3 — insert — ambiguity — `house_absorbed_refurb_cents` left as posted — `services/derive.py:499`
- §3.9 Abandonment depth 4 — revise — mismatch — waterfall re-run restamps this invoice's money; exact list of versioned entities, bidder and payments excluded — `services/derive.py:589`
- §5 Error handling — insert — ambiguity — `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500 outside the domain catalogue — `app.py:50`

Nothing under `implementation/`, `test_suite/` or `test_helpers/` was touched; `SCAFFOLD*.yaml` and `worklog.md` were not read.

---

## Pipeline complete

Final artifact inventory in `tasks/task_2244_heavy_equipment_auction_global_bidding/`:
- `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`
- `test_helpers/` (9 modules), `test_suite/` (conftest + 14 test modules, 100 tests)
- `workspace/INSTRUCTION.md`, `workspace/PRD.md`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md`
- `workspace/implementation/` (21 files, 87 endpoints, `start.sh`) + `results.1.json` … `results.8.json`, all 8 rounds 100/100
