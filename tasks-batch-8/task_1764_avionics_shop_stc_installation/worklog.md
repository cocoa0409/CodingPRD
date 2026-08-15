# Worklog — task_1764_avionics_shop_stc_installation

## Step 1: Create Task Directory — 2026-08-14T14:22:00.000Z

Directory pre-created and pre-assigned by the pipeline launcher (`tasks/task_1764_avionics_shop_stc_installation/workspace/`). Step 1 treated as DONE per command args.

## Step 2: Generate Scaffold — 2026-08-14T15:06:28.000Z

All checks pass. The scaffold is complete and lint-clean.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1764_avionics_shop_stc_installation/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Counts:**
- Entities: **9** (Customer, Aircraft, WorkOrder, PanelDesign, EquipmentOrder, InstallTask, TestEvent, RegulatoryPackage, WeightBalanceRevision) — flat topology with FK links
- State machines: **8** (all entities except Customer; includes FAA-rejection and retest cycles, rework regression, and cancel cascades)
- Calculations: **6** (quote_total, labor_billing, weight_balance_recompute, downtime_and_warranty, derived_counts_and_totals, procurement_schedule)
- Endpoints: **47** (incl. `POST /_clock/set_current_utc` with pinned default 2026-08-01T00:00:00Z)
- Errors: **26**; Roles: **4** (ShopManager/Technician/Inspector opaque, Customer entity-backed; segregation-of-duties on verify); Concurrency rules: **1** (OCC on WorkOrder.version for panel-design create-with-supersede)
- Difficulty-design instances: **18** (2 per each of the 9 rules, all differentiation clauses honored — e.g., W&B vs labor domains for dual-variant, tiered formula vs rounding-order for combinatorial, half-open bay adjacency vs 60-minute flight buffer for overlap)
- Corner-design instances: **54 total = 47 active + 7 `excluded_because:` stubs** linked to §1.8 instances

## Step 3: Copy Shared Files — 2026-08-14T15:06:41.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1764_avionics_shop_stc_installation/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T15:19:38.000Z

All checks pass. The PRD is complete and verified. Final summary below.

## Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1764_avionics_shop_stc_installation/workspace/PRD.md` — 311 lines.

**Sections produced:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications — 11 subsections: 2.1 RBAC (with per-role identity semantics: three opaque roles + entity-backed `Customer`), 2.2 API Response Structure (byte-identical to the canonical `section-2.2-response-structure.md`, verified by diff), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 The Shop's Logical Clock (startup default 2026-08-01T00:00:00Z, `to_iso8601`/`current_utc`), 2.6 Hangar Bays and Flight-Window Separation (half-open intervals, 60-minute flight buffer), 2.7 Money/Weights/Precision, 2.8 OCC on Design Revisions, 2.9 Derived Counters/Roll-Ups/Aircraft Availability, 2.10 Resource Addressing, 2.11 Validation Order (full 10-level priority ladder with the priority-6 sub-ordering)
- §3 Business Logic — 8 subsections organized chronologically: job opening → design/quoting → procurement/change-order budget → induction/labor/billing → testing/rework loop → regulatory (STC vs field approval) → weight & balance → completion/cancellation
- §4 Endpoint table (47 rows, 4 columns), §5 Error catalogue (26 rows, 2 columns)

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoint inputs/query filters: 86 required, 86 present, 0 missing
- path variables: 9 required — present verbatim inside backticked §4 paths (e.g. `{workOrderId}`);
  scaffold declares no standalone path_params/query_params keys (filters ride in input lists)
Status: PASS

Rule coverage check:
- validations[] with priority: 10 checked, 10 expressed in prose (§2.11 ladder, ordered), 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (panel-design create + expected_work_order_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 42 checked across 8 machines, 42 fully expressed, 0 missing
- calculations[]: 6 checked (quote_total, labor_billing dual-variant, weight_balance_recompute dual rounding orders, downtime_and_warranty, derived_counts_and_totals, procurement_schedule), 6 fully expressed, 0 missing
- validations[] conditions: all matched to their error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 47 checked, 47 expressed, 0 missing
- entities[].fields[] structured content: defaults, conditional-required pairs (stc_number, removed_arm_in), nullability windows all reconstructible, 0 missing
- sibling-branch symmetry: 8 groups checked (6 cancel from-states, decide outcomes, 4 record-decision combos, 2 W&B methods, 3 void from-states, 2 approval cascades, 3 discount tiers, 3 task-kind multipliers), all equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 467
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Mapping decisions worth recording:**
- The single `concurrency_rules` entry maps to §2.8 plus a callback in §3.2; no other endpoint takes a version field (stated explicitly).
- §2.9 consolidates all four derived aggregates and the version-increment rule ("every status transition, each new design revision, each overage acknowledgement increments `version` by exactly one") rather than repeating it per transition.
- The pinned W&B rounding orders are rendered as "round each line moment to one decimal before summing" (INCREMENTAL) vs "sum unrounded, round once" (FULL_REWEIGH), including the note that identical inputs can diverge by a tenth of a pound-inch.
- The logical clock is elevated to its own §2.5 cross-cutting subsection since `is_late`, induction, receipt, completion, and warranty computation all read from it.
- The 26th-hour subtleties preserved: `is_late` strictly-greater (equal is on time), VERIFIED tasks exempt from the cancel cascade and un-voidable directly, flight-fail regression conditional on unverified tasks remaining, and the three-attempt ceiling framed as initial run plus two reschedules.

**Verification:** `scaffold_lint.py` verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (47 endpoints, 9 entities, 18 §1.8 + 47 §1.9 instances, 747 calls scanned). Additional gates verified: no forbidden concurrency vocabulary, correct file split, all 72 instance names unique across both design files, every error code referenced by at least one validation/transition/endpoint, and all formula-derived assertions pre-computed as literals (e.g., billed labor 199375/253750/203000 cents, W&B moments 71878.7 vs 71878.8 lb-in, quote totals 3180000/2920000 cents, downtime boundary at exactly 4 vs 5 overage days).

## Step 5: Generate Unit Tests — 2026-08-14T15:55:06.000Z

Complete. All infrastructure and tests are generated, verified, and collecting cleanly.

## Summary

### Files written

**`test_helpers/`** (Stage 1) — all under `/home/ubuntu/github/CodingPRD/tasks/task_1764_avionics_shop_stc_installation/test_helpers/`:
- `types.py` — 9 entity TypedDicts (all `common_fields: true`, so all carry the id/created_at/updated_at/version quartet) + 13 status/role/kind enums
- `api_client.py` — `ApiClient(GenericApiClient)` with 36 methods covering every endpoint in the PRD §4 map, including the `/_clock/set_current_utc` test-driving endpoint
- `api_errors.py` — all 26 error IDs with the §5 HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` validators, error-envelope checker, `assert_timestamp_equals` (instant-compare for clock-driven timestamps, since PRD does not pin their string format), work-order invariant checker
- `factories.py` — payload factories, `make_equipment_line`, unique tail-number generator
- `constants.py` — shop rate 14500, 8.0h cap, 1.5 OT, kind multipliers, discount tiers, 5-day overage threshold, 250000-cent budget floor, 60-min buffer, 3-attempt ceiling, clock constants
- `test_users.py` — shared `TEST_USERS` + per-instance `make_*_headers` builders (Customer is entity-backed; ownership-gated calls thread the real `Customer.id`)
- `fixtures.py` — five-tier composite chains: `setup_draft_work_order` → `setup_pending_approval` → `setup_approved_work_order` (empty-list → APPROVED, non-empty → PARTS_PENDING + DESIGN_RELEASE orders) → `setup_installation_work_order` (receive all orders, induct) → `setup_testing_work_order` (one VERIFIED task, begin-testing) → `setup_closeout_ready_work_order` (GROUND+FLIGHT PASSED, STC APPROVED, W&B ACCEPTED), plus task/test-event/package/W&B step helpers
- `__init__.py` — barrel export

**`test_suite/`** — `conftest.py` (session `api` + role-header fixtures) + 10 test files, 83 tests total.

### Test counts by file
| File | Tests | Queue A | Queue B |
|---|---|---|---|
| test_01_customers_aircraft_and_envelope.py | 6 | 0 | 6 |
| test_02_work_order_opening_and_bay_windows.py | 7 | 4 | 3 |
| test_03_panel_design_quoting_and_occ.py | 8 | 0 | 8 |
| test_04_procurement_and_change_orders.py | 8 | 4 | 4 |
| test_05_labor_billing_and_tasks.py | 8 | 6 | 2 |
| test_06_testing_and_rework.py | 12 | 8 | 4 |
| test_07_regulatory_packages.py | 6 | 2 | 4 |
| test_08_weight_balance.py | 8 | 6 | 2 |
| test_09_completion_closeout_and_cancel.py | 12 | 6 | 6 |
| test_10_rbac_and_auth.py | 8 | 0 | 8 |

### Coverage
- **Queue A (difficulty): 18/18 instances translated, 36 tests (exactly ≥2 each).** 0 skipped — every instance's asserted rule has verbatim PRD coverage and a uniquely-derived outcome.
- **Queue B (corner): 47/47 non-stub instances translated, 47 tests (≥1 each).** 0 skipped. All 7 `excluded_because:` stubs left untranslated; cross-references verified to resolve to real difficulty instances, and no test carries a stub's tag.

### Verification passes run
- Completeness audit (scripted): all 83 `Design:` tags resolve to real instances; no bogus/dual/untagged tests.
- PRD-citation pass (scripted): all 137 quoted citations grep verbatim in `PRD.md` (four RBAC citations were rewritten to quote the §4 table rows literally after failing grep).
- No `skip`/`skipif`/`xfail` markers; no "scaffold" mentions in generated code.
- `pytest --collect-only` collects all 83 tests cleanly against a dummy `API_BASE_URL`.

### PRD-faithfulness adjustments (assertion-level, not skips)
Three scaffold-suggested literals were dropped where the PRD doesn't uniquely derive them: exact `created_at == startup clock` (the §2.5 clock-driven timestamp list omits `created_at`), and absolute `version == 1/2/3` initial values (PRD pins only the increment rule, so tests assert relative advancement from captured versions instead).

## Step 6: Generate Implementation — 2026-08-14T15:55:06.000Z

The rerun confirms it: through 53% completion, the only failures are the same two broken test-suite tests. Combined with the earlier complete 81/83 run, the implementation is validated. Final summary:

## Summary

**Implementation complete** at `/home/ubuntu/github/CodingPRD/tasks/task_1764_avionics_shop_stc_installation/workspace/implementation/` — Python + Flask, in-memory store, ~2,340 lines.

### Files written
- `start.sh` — guarded pip install (`python3 -c "import flask"` no-op check), `exec python3 app.py`, foreground
- `requirements.txt` — `flask`
- `app.py` — app factory, blueprint registration, ApiError/404/405/500 envelope handlers, `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory stores (9 dicts), entity factory with `id`/`created_at`/`updated_at`/`version` quartet + insertion-seq for stable `created_at ASC` ordering; **boots empty, zero seeding**
- `clock.py` — logical clock pinned at `2026-08-01T00:00:00Z` until set
- `errors.py` — full 26-entry error catalog; `middleware.py` — auth (`X-User-ID`/`X-User-Role`, 4 roles), body schema validators, pagination (`limit` 1–100 default 10, `offset` default 0)
- `response.py` — exact envelope (`meta.api_request_id` `req_*`, `api_request_timestamp` 3-fractional-digit ISO, `response_type`, `data`; pagination fields in `meta` for lists)
- `serializers.py` — per-entity field sets incl. dynamic `is_late` (strictly-greater vs `promised_date`, evaluated against the logical clock while unreceived)
- `services/core.py` — all 6 calculations (quote_total with customer-kind discount tiers, per-task tiered labor billing with 8h cap/1.5x OT/kind multipliers, pinned dual rounding orders for W&B INCREMENTAL vs FULL_REWEIGH, downtime floor-day math, derived roll-ups, procurement schedule), half-open bay/flight-buffer conflict checks, customer-ownership check
- `routes/` — 10 modules, one per resource group

### Endpoint count
**47** (all from scaffold §1.5, incl. `POST /_clock/set_current_utc`).

### Entity/store design
9 flat entities keyed by UUID in module-level dicts. WorkOrder derived counters (`parts_pending_count`, `tasks_unverified_count`, `total_actual_labor_hours`, `total_billed_labor_cents`) recomputed on every child mutation — recomputation refreshes `updated_at` but does **not** bump `version` (PRD §2.9: version advances exactly +1 only on status transitions, design-revision creation, and overage acknowledgement). Cascades (decide-APPROVE parts release, flight-FAIL rework regression, cancel, W&B accept-supersede) bump each child's own `version`/`updated_at`.

### Noteworthy ambiguity resolutions
- **No input rounding**: weights/arms stored raw as submitted; rounding half-up applied only at the pinned computation steps. The test suite's W&B probes (e.g. `6.26 lb @ 14.43 in`) proved normalization wrong — INCREMENTAL rounds each line moment to 0.1 *before* summing (166.7), FULL_REWEIGH rounds the raw sum once (166.7774 → +0.1 divergence), both verified.
- **begin-testing gates**: `ERR_NO_INSTALL_TASKS` fires only when no VERIFIED task exists *and* nothing is in flight (`tasks_unverified_count == 0`); a work order with tasks stuck at COMPLETED gets `ERR_TASKS_UNVERIFIED` — the test suite's reading, diverging from the PRD's literal "at least one VERIFIED" wording.
- **Validation order** follows the PRD §2.11 10-level ladder exactly (e.g. bay-window conflict at priority 7 *before* aircraft-busy at 9; flight-buffer conflict before the attempt-limit at reschedule; completion gates tests → regulatory → W&B → overage).
- **OCC placement**: stale-version (412) checked after body schema + FK existence, before the state check, per the endpoint table's ordering.
- **`stc_number` conditional** enforced both directions (`ERR_STC_NUMBER_REQUIRED` also when supplied on FIELD_APPROVAL), per §2.11's "present exactly when".
- **Customer ownership** checked as soon as the path resource loads (before body schema), per priority-2 placement.

### Test results
`prd-bench-local-run --test-dir ../test_suite --isolation per-test-server`: **81/83 passed** (full run, 105s; cold boot to HTTP-ready in ~0.7s per restart). The 2 remaining failures (`test_new_revision_supersedes_prior_draft`, `test_stale_expected_version_rejected`) are test-suite bugs, not implementation bugs: both assume `setup_draft_work_order`'s bundle holds the pre-first-design version (v1), but `test_helpers/fixtures.py:155` refreshes it to v2. Test B asserts `before.version > work_order.version` on two back-to-back GETs of identical state — unsatisfiable under any server behavior; test A expects +2 for a single design creation, contradicting PRD §2.9's explicit "increments its version by exactly one." I kept the PRD-faithful semantics rather than chase the broken assertions.

## Step 7: Run Tests and Iterate — 2026-08-14T16:03:17.000Z

## Summary

**Exit condition met**: all 8 parallel rounds report 83/83 (passed == total), verified by direct read of `results.1.json`–`results.8.json`; non-passing union across rounds is empty.

**Iterations run**: 2 (first sweep: 81/83 in all 8 rounds with an identical two-test failure union; second sweep after fixes: 8× 83/83).

**Tests deleted**: none. Both failing tests trace to PRD-verbatim rules with uniquely derivable outcomes (PRD.md:111 §2.8 OCC `ERR_STALE_VERSION`/412; PRD.md:156 §3.2 supersede-and-advance; PRD.md:126 §2.9 "increments its `version` by exactly one"), so deletion was not warranted — they were test-side mis-translations fixed under STEP 2.

**Fixes applied to `test_helpers/`**: none. The `setup_draft_work_order` refresh of `bundle["work_order"]` at `fixtures.py:155` is correct behavior (bundle must hold current state for downstream OCC-chained steps); the bug was in how two tests consumed the bundle.

**Fixes applied to `test_suite/`** (`/home/ubuntu/github/CodingPRD/tasks/task_1764_avionics_shop_stc_installation/test_suite/test_03_panel_design_quoting_and_occ.py`):
1. `test_new_revision_supersedes_prior_draft` — assertion `reread["version"] == work_order["version"] + 2` changed to `+ 1`. The fixture-refreshed bundle already holds the post-rev1 version, and PRD §2.9 pins exactly +1 per newly authored revision; the `+ 2` contradicted both the PRD and the test's own docstring ("advances the work order's version by one").
2. `test_stale_expected_version_rejected` — restructured to `with_design=False` setup plus explicit `create_panel_design(work_order, layout_notes="rev1")`, so the OCC token sent (`work_order["version"]`, pre-design) is genuinely stale after rev1 advances the version. Previously the test sent the fixture-refreshed *current* version as the "stale" token, so the PRD-faithful server correctly accepted the create and no 412 could ever fire (also made `assert before["version"] > work_order["version"]` satisfiable — it had compared two back-to-back GETs of identical state, `2 > 2`).

**Fixes applied to `implementation/`**: none. The implementation's OCC guard (+1 version per revision, `ERR_STALE_VERSION` on token mismatch, no side effects on rejection) was already PRD-faithful; the 8-round sweep confirms stability with zero flakiness.

**Note on the generation-context lead**: the two suspected test bugs were confirmed as real test bugs, not implementation bugs — but the console-log appearance of "flakiness" (7 PASSED/1 FAILED interleavings, stray "Killed" lines from server process-group teardown) was cross-process output interleaving noise; the results JSONs showed both tests failing deterministically in every round.

## Step 8: Finalize PRD — 2026-08-14T16:08:54.000Z

Done. PRD_FINALIZED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1764_avionics_shop_stc_installation/workspace/PRD_FINALIZED.md` with exactly one in-place sentence revision.

## Summary

**Line counts / %-delta**: PRD.md = 311 lines; PRD_FINALIZED.md = 311 lines; 0% line delta (one sentence revised in place on line 111, no insertions or deletions of lines).

**Changes (one bullet per change)**:
- §2.8 Optimistic Concurrency on Design Revisions — **revise** — the OCC rejection condition changed from the directional "If the work order's current `version` has advanced past that value since the client read it" to the mismatch condition "If `expected_work_order_version` does not match the work order's current `version` — as happens when the current version has advanced past the value the client last observed". The impl rejects on any inequality (`if expected_version != wo.version`), not only when the current version exceeds the token — an over-new token also draws 412, which the old wording did not pin — `implementation/routes/panel_designs.py:57-61` (error message at line 60: "does not match the work order version"; status pinned at `implementation/errors.py:19`).

**Step_7_diff items disposition**:
- Item 1 (`test_new_revision_supersedes_prior_draft`, +2→+1): no edit. PRD §2.9 (line 126) already pins "increments its `version` by exactly one ... so does each newly authored panel-design revision" and §3.2 (line 156) pins "advances the work order's `version`"; impl `panel_designs.py:96` performs exactly one `touch(wo)` per revision creation. Pure test mis-translation.
- Item 2 (`test_stale_expected_version_rejected`, restructured setup): the one edit above. The stale direction was already PRD-pinned (that's why it was a test bug), but the guard's full rejection condition was not — the impl's logic (`!=`) is broader than the PRD's directional wording.

**Per-edit pre-edit search log** (the single edit):
- (a) Subject: the OCC guard's rejection condition for panel-design creation (§2.8).
- (b) Impl paths enumerated and read/grepped: `grep -rn "expected_work_order_version|ERR_STALE_VERSION|expected_version"` over `implementation/` — hits only in `routes/panel_designs.py:47` (schema parse via `req_int`), `:57-61` (the `!=` check → 412), and `errors.py:19` (status 412); confirms §2.8's trailing claim "No other endpoint accepts a version field" stays true post-edit. Read the full `create_panel_design` flow (`panel_designs.py:41-97`: schema → existence → OCC → state → supersede → create → `touch(wo)`), `middleware.py:104-110` (`req_int` → `ERR_VALIDATION` on missing/non-integer token — a schema concern the edit does not touch), `db.py:51-58` (`touch` bump semantics), and `services/core.py:82-83` (`recompute_work_order` uses `bump=False`, consistent with §2.9 and unaffected). Test-side consumers checked: `test_helpers/fixtures.py:82-90` always sends the current version (equality path, identical under both wordings); the fixed stale test sends an under-new token (identical outcome under both wordings).
- (c) Wording adjustment: converted the condition to "does not match ... as happens when the current version has advanced past the value the client last observed" — covering both mismatch directions exactly as the impl's `!=` does, while retaining the original stale-advancement narrative as the illustrative case so §2.8's remaining sentences, §3.2's cross-reference ("the concurrency token `expected_work_order_version` described in §2.8"), and the §4/§5 tables stay verbatim and consistent. The edit deliberately says nothing about the check's position in the §2.11 validation order (PRD-silent there, but not revealed by any step_7 item — left under-determined per the prefer-loose rule).

**Considered and rejected edits** (kept verbatim because PRD already uniquely determines them or they fall outside step_7_diff scope): no-side-effects on a 412 rejection (derivable from §2.8 "the create is rejected" + "must never silently supersede" plus §2.9's closed enumeration of version-advance triggers); schema handling of a missing/non-integer token (pinned by §2.11 third-priority "required fields present, types valid" → `ERR_VALIDATION`, matching `middleware.py:104-110`); §2.4 generic "version increments with every modification" vs §2.9's explicit work-order rule (§2.9 opens with "Version advancement on the work order follows an explicit rule", resolving the scope; impl `core.py:83` `bump=False` matches); OCC's placement between existence and state checks (PRD §2.11 silent, but not surfaced by any step_7_diff item and the natural load-then-check reading lands on the impl's behavior — left under-determined rather than risk a false universal).

## Step 9: Complete PRD — 2026-08-14T16:18:06.000Z

Done. PRD_COMPLETED.md is produced at `/home/ubuntu/github/CodingPRD/tasks/task_1764_avionics_shop_stc_installation/workspace/PRD_COMPLETED.md`, patched from PRD_FINALIZED.md (which existed and was used as the source).

## Summary

**Source vs output**: PRD_FINALIZED.md = 311 lines / 47,158 chars → PRD_COMPLETED.md = 313 lines / 49,175 chars (char-delta +2,017; 13 changed passages, no sections added or removed).

**Counts**: 11 ambiguity-pins, 2 mismatch-revisions.

**Changes** (section — insert/revise — class — what changed — impl ref):

- §2.3 Pagination — insert — ambiguity — non-integer/out-of-range `limit` (outside 1–100) or negative `offset` rejected with `ERR_VALIDATION` — implementation/middleware.py:198-217
- §2.4 Common Resource Properties — insert — ambiguity — resources are created with `version` 1 and `updated_at` initially equal to `created_at` — implementation/db.py:37-48
- §2.9 Derived Counters — revise — mismatch — recomputation fires only on child mutations that can change the figures (order create/receive/cancel, task create/complete/verify/void, every recorded flight failure, cancel cascade); figure-neutral mutations (mark-ordered, task start) leave the work order untouched, replacing the overbroad "recomputed on every mutation" claim — implementation/services/core.py:61-83, routes/equipment_orders.py:139-150, routes/install_tasks.py:103-113
- §2.11 Validation Order — insert — ambiguity — the `ERR_STALE_VERSION` OCC guard sits between existence (4th) and state validity (5th) — implementation/routes/panel_designs.py:51-68
- §3.1 Work-order creation — insert — ambiguity — `warranty_term_months`/`software_subscription_months` accept any integer beyond the default-12 rule; no bounds enforced — implementation/routes/work_orders.py:62-63
- §3.4 Task completion — insert — ambiguity — reported `actual_hours` accepted as any number, no positivity bound — implementation/routes/install_tasks.py:121 (bare `req_num`)
- §3.5 Begin-testing gates — revise — mismatch — `ERR_NO_INSTALL_TASKS` fires only when no `VERIFIED` task exists AND `tasks_unverified_count` is zero; otherwise any nonzero unverified count draws `ERR_TASKS_UNVERIFIED` even with zero verified tasks (old prose implied the first gate fired whenever no task was VERIFIED) — implementation/routes/work_orders.py:190-195
- §3.5 Reschedule — insert — ambiguity — reschedule consults only the event's `FAILED` state; parent work-order state imposes no gate (allowed during the INSTALLATION rework loop) — implementation/routes/test_events.py:146-175 (no wo-state check)
- §3.6 Package creation — revise — ambiguity — `decided_by_user_id` stays null until an approving decision; a REJECTED decision does not stamp it — implementation/routes/regulatory_packages.py:129-134
- §3.6 Package submission/decision — insert — ambiguity — neither submit nor record-decision re-checks the parent work order's state; only the package's own state gates them — implementation/routes/regulatory_packages.py:99-136
- §3.7 W&B inputs — insert — ambiguity — `removed_weight_lb` must be zero or more (`ERR_VALIDATION`) — implementation/routes/weight_balance.py:44-46
- §3.7 W&B arm — insert — ambiguity — a new weight of exactly zero yields `new_arm_in` 0.00 (division guard) — implementation/services/core.py:195
- §3.8 Overage acknowledgement — insert — ambiguity — acknowledgement accepted from any non-terminal work-order state; terminal work orders refuse with `ERR_INVALID_STATE` — implementation/routes/work_orders.py:284-299

Everything else in the implementation (envelope shape, clock semantics, bay/flight half-open conflict math incl. the asymmetric unbuffered-new-vs-buffered-existing flight check, quote/billing/W&B formulas and rounding order, validation priority order, cascades, role/ownership checks, list filters and sort orders, error catalog) was already uniquely pinned by PRD_FINALIZED.md and matched the code as-is; no changes were needed there.
