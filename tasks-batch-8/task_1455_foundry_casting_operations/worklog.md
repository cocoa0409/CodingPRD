# Worklog — task_1455_foundry_casting_operations

## Step 1: Create Task Directory — 2026-08-13T09:02:00.000Z

Task directory `tasks/task_1455_foundry_casting_operations/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per invocation instructions. No index scan performed; no other task_* directory touched. User directive: generate task harder than expert level.

## Step 2: Generate Scaffold — 2026-08-13T10:35:00.000Z

Scaffold generation complete. All three artifacts are written and the linter is clean.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
Coverage
  §1.5 endpoints declared:    59
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     63
  Calls scanned (§1.8+§1.9):  1334

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Summary

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1455_foundry_casting_operations/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

**Counts**
- Entities: **14** (Foundry, Customer, Pattern, CustomerOrder, Equipment, MeltHeat, PourSlot, Mold, Casting, InspectionReport, ScrapRecord, ReturnLot, SandBatch, WarrantyClaim)
- State machines: **11** — four cyclic (MeltHeat correction loop, WarrantyClaim info/appeal loops, SandBatch reclaim loop, Casting rework loop), one parallel-dimension (Casting routing × quality), one branching fork with divergent side effects (InspectionReport disposition), compound auto-transitions (CustomerOrder, Mold)
- Calculations: **16**, incl. 2 dual-variant (scrap credit provisional/final on ScrapRecord; warranty credit STANDARD vs MACHINING_ALLOWANCE on WarrantyClaim), combinatorial modes (a) shrink-allowance branch+cap, (b) sand per-event rounding, (c) frozen-baseline corrective-charge order, plus two pinned mass invariants (alloy, sand)
- Validations: **10** priority tiers (auth → role/ownership → existence+tenant scoping → state → safety/SoD → referential → constraint → temporal → fiscal → posture)
- Endpoints: **59** (32 POST/action incl. `/_clock/set_current_utc` with the mandated 2026-08-01 default; 27 GET for FK reverse-reachability)
- Error catalog: **35** codes, all triggerable and referenced
- Roles: **8** (7 opaque + `Customer` entity_backed), segregation-of-duties model with two SoD rules (spectro certifier vs disposer; claim approver vs settler)
- Concurrency: 3 OCC rules (heat samples, heat charges, run-ops) — all true create-with-supersede races, no forbidden vocabulary

**§1.8 difficulty design**: 9 rules × 2 instances = **18** (all at maximum depth): dual-variant across two entity domains; combinatorial modes (a) and (c); cascades of depth 4 (SCRAP disposition → casting → scrap record → return lot → foundry) and depth 3 (LOI fail → batch discard → mold quarantine → slot cancel); priority conflicts state-vs-fiscal and safety-vs-temporal; boundaries on count (==qty) and weight (==capacity); temporal overlap with half-open+buffer vs closed-inclusive semantics; both mass invariants asserted with computed literals (e.g., 170.0 provisional credit, 4.14 kg corrective carbon, 65000 vs 250000 warranty credits).

**§1.9 corner design**: **66 instances** (63 active + 3 excluded stubs) — entities 6, state_machines 18, calculations 6, validations 8, endpoints 2, errors 14, rbac 6, cross_cutting_layers 5, consistency_model 1.

**Notable design decisions**
- Endpoint count (59) intentionally exceeds the Expert 20–32 guideline: with 14 entities and ~20 FKs, the lint's FK reverse-reachability rule (f) mechanically requires 27 GETs; the skill's stated hard floors and lint were prioritized over the soft upper guideline.
- Foundry posture (OPEN/CURTAILED/EMBARGO from IN_SERVICE sand) gates only pour-slot booking — gating mold creation was provably unreachable because per-batch sand checks always fire first (caught and fixed during self-review).
- `DENIED` is non-terminal on WarrantyClaim (appeal loop); `SETTLED` is the only terminal state.
- Archetypes prioritized per diversity guidance: compliance/audit primary, temporal windowing secondary; flat topology; cyclic state shape; self-referential pattern revisions; SoD role model.
- All formula-derived asserts were computed by executing the formulas in Python (per §1.8 contract item 7).

## Step 3: Copy Shared Files — 2026-08-13T10:36:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1455_foundry_casting_operations/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T10:56:00.000Z

PRD generation complete. Final report below.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1455_foundry_casting_operations/workspace/PRD.md` — 326 lines (327 counting trailing newline).

**Section list**
- §1 Introduction (2 paragraphs: traceability-chain framing, then compliance-audit + logical-clock design pressures)
- §2 Global Specifications: 2.1 RBAC, 2.2 API Response Structure (verbatim), 2.3 Pagination, 2.4 The Logical Clock, 2.5 Resource Identity and Common Fields, 2.6 Optimistic Concurrency Control, 2.7 Units/Precision/Rounding, 2.8 Mass-Balance Ledgers, 2.9 Foundry Posture and Production Gating, 2.10 Validation Order and Error Precedence, 2.11 Resource Scoping and Cross-Foundry References
- §3 Business Logic (9 subsections, lifecycle-timeline grouping): 3.1 Site Commissioning & Ops Epoch, 3.2 Pattern Tooling/Shrink/Qualification, 3.3 Order Intake & Pipeline, 3.4 Melt Deck (Charging/Certification/Tap), 3.5 Molding & Pour Scheduling, 3.6 Shakeout/Finishing/X-ray Disposition, 3.7 Scrap & Remelt Accounting, 3.8 Sand Reclamation & Quarantine Cascade, 3.9 Warranty Claims & Settlement
- §4 Endpoint Definitions (59 rows, 4 columns), §5 Error Code Catalogue (35 rows, 2 columns)

**Zero-silence self-audit (scaffold → PRD prose trace)**

- `entities[].fields` + endpoint input/query/path identifiers: **120 required, 120 present, 0 missing** (mechanical backtick diff)
- `state_machines[].transitions`: **51/51** fully expressed (from/to states, every precondition paired with its error id, every side effect) — includes all tap sibling-branch errors (`ERR_HEAT_NOT_CERTIFIED` vs `ERR_INVALID_STATE` vs `ERR_ALREADY_TERMINAL`) and all four MRB disposition branches at equal density; terminal states named for all 12 machines (PourSlot/Mold terminals added in a patch pass after audit)
- `calculations[]`: **15/15** expressed as precise prose with reconstruction-safe wording — shrink-allowance caps (6.0/2.5 mm) and four shrink factors, 0.3 mm equality-passes tolerance, inclusive spectro bounds + CE formula in words, frozen-baseline AUTO_CORRECT (midpoint target, purity 1.00, 2 dp per element, recompute-after), 0.85 provisional yield with weigh-delta reconciliation, dual warranty variants (rounding before budget check), pinned per-event 0.1 kg reclaim rounding (33.35×3 → 100.2 counterexample), posture boundary 500/500.01 kg, pipeline ceil cap, both daily-load legs with equality-allowed, half-open+buffer vs closed-window interval contrast, last-cavity remainder rule, both mass invariants
- `validations[]` (priorities 1–10): **10/10** expressed as an explicit ordered precedence chain in §2.10, every condition matchable to its error id; all 35 error ids appear in §2/§3 prose (0 missing)
- `concurrency_rules[]`: **3/3** (samples, charges, run-ops) with endpoint, `expected_*_version` field, mismatch rejection, `ERR_STALE_VERSION`/412; explicit "no other endpoint takes a version field"; no race-framing language
- `endpoints[].side_effects`: **59/59** covered in §3/§2 narratives
- Field structured content (defaults/initials): all expressed — `overage_pct` 0.10, `freight_cents` 0, zero counters, null-until fields (`fulfilled_at`, `actual_weight_kg`, `disposition`, `settled_credit_cents`, `certified_by_user_id`, `pour_slot_id`, `parent_pattern_id`), empty `maintenance_windows` at registration

**Hard contract reports**
- Contract 1 (Field-Name Coverage): 120/120 present, 0 missing — **PASS**
- Contract 2 (Rule Coverage): all six high-risk categories + tail verified, 0 silent — **PASS**
- Contract 3 (§3 Path Purity): 623 backtick tokens scanned in §3, 0 path/method/combo violations — **PASS**
- Plus: §2.2 byte-verbatim against `section-2.2-response-structure.md` — PASS; fuzzy-word scan — clean (one narrative "about" replaced); pseudocode-operator scan (`==`, `<=`, `min(`, etc. outside tables/code) — 0 leaks

**Notable wording/scattering decisions**
- Claim-filing order-state guard mapped to `ERR_INVALID_STATE` (the scaffold's priority-6 entry covers the check but nominates no claim-specific error id; `ERR_INVALID_STATE` is the only consistent reading).
- Posture gating written as slot-booking-only, following the `foundry_posture` calculation and error-catalog text over the looser priority-10 summary line; the "posture evaluated after per-resource checks" precedence is stated explicitly.
- Scattering: `machining_allowance_pct` introduced at order intake (§3.3) but its commercial effect deferred to settlement (§3.9); `return_lot_id` credited at disposition (§3.6) with the credit mechanics in §3.7; posture constants in §2.9 with gate consequences re-narrated at booking (§3.5); quarantine cascade introduced in §3.5 as a forward reference and fully specified in §3.8.
- The RETURN_LOT charge chemistry source (lot's `assay_composition`) is stated as the only consistent reading of the scaffold's projected-chemistry inputs.
- §4 descriptions carry the query-filter names in backticks, which covered all list-endpoint query params for Contract 1 without a schema dump.

## Step 6: Generate Implementation — 2026-08-13T11:35:00.000Z

Fresh-boot contract verified on an OS-allocated free port: server boots via `bash start.sh`, serves the correct envelope from an empty store, and was killed cleanly. The implementation is complete.

## Summary

**Task**: `task_1455_foundry_casting_operations` — full Python + Flask implementation generated purely from INSTRUCTION.md + SCAFFOLD.yaml + PRD.md (no sibling tasks or test directories consulted).

### File list (all under `/home/ubuntu/github/CodingPRD/tasks/task_1455_foundry_casting_operations/workspace/implementation/`)
- `start.sh` — guarded launcher (skips pip install when flask importable, `exec python3 app.py`)
- `requirements.txt` — flask
- `app.py` — Flask app, ApiError/404/405/500 envelope handlers, `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory dict stores (start empty; no seeding), logical clock defaulting to exactly `2026-08-01T00:00:00Z`, `touch()` (updated_at + version++ on every mutation)
- `errors.py` — all 35 error IDs with exact HTTP statuses from the catalog
- `response.py` — envelope `{meta, response_type, data}`; Decimal→float, datetime→ISO-3-fractional-digit serialization; pagination meta in `meta`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (8 roles), limit/offset pagination (default 10, clamp 1..100), `created_at`-ascending sort
- `util.py` — Decimal round-half-up helpers (2dp kg, 1dp pattern axes, 4dp chemistry, 0.1kg reclaim events), second-precision ISO parsing, payload validators
- `services.py` — posture/alloy/pipeline recomputation, order counters, casting apportionment (remainder to last cavity), quarantine cascade, run-ops sweep, chemistry projection, spectro certification (incl. CE = C + Si/3 + P/2), frozen-baseline AUTO_CORRECT
- `routes/` — 15 modules: clock, foundries, customers, patterns, orders, equipment, heats, pour_slots, molds, castings, inspections, scrap, return_lots, sand, claims

### Endpoint count
**59** routes implemented — the full PRD section 4 table (incl. `POST /_clock/set_current_utc` outside `/api`).

### State machine count
**11** state machines: Pattern (incl. transient QUALIFICATION and revision supersede), CustomerOrder, MeltHeat (charge/sample correction loop), PourSlot, Mold, Casting (parallel routing × quality dimensions), InspectionReport, ScrapRecord (provisional→weighed), ReturnLot, SandBatch (reclaim loop + quarantine cascade), WarrantyClaim (review loop + single appeal + SoD settle).

### Boot / start.sh
`bash start.sh` from `implementation/`: guards dependency install behind `python3 -c "import flask"` (no-op on reboots), then `exec python3 app.py` in foreground binding `0.0.0.0:$PORT` (default 10000). Store is module-level dicts — every fresh process boots empty, so per-test-server restarts are clean.

### Key fidelity decisions
- Validation precedence follows PRD §2.10 (auth → role/action-scope/ownership → existence incl. cross-foundry-as-404 → state → safety → referential → structural → temporal → fiscal → posture-last); posture gates slot booking only (PRD wins over scaffold's priority-10 wording).
- OCC: `expected_heat_version` (charges/samples), `expected_foundry_version` (run-ops) → 412.
- Decimal everywhere for kg/cents; casting remainder to last cavity; per-event 0.1kg reclaim rounding (3 × 33.35 → 100.2); boundary rules (0.3mm inclusive, 500kg CURTAILED vs 500.01 OPEN, inclusive spectro bounds, closed furnace windows vs half-open+buffer slots).

### Smoke verification
Manual smoke boots succeeded repeatedly: server started on `$PORT`, endpoints responded, server killed. Six scenario scripts (≈120 assertions) passed covering: pattern dims/qualify/revisions, orders and pipeline cap, heat charge/sample/AUTO_CORRECT math (5.18 kg correction verified numerically), OCC 412s, tap capacity/windows, slot overlap+buffer, pour and cooling via run-ops, shakeout sand ledger, inspections/rework loop/SoD, scrap two-phase credit, return-lot assay/downgrade/consume, sand test/reclaim/quarantine cascade (molds scrapped, slot cancelled, pipeline recomputed), posture boundaries and gating, warranty claims (STANDARD vs MACHINING_ALLOWANCE credits, budget, SoD, appeal, window expiry), RBAC negatives, ownership, pagination, and terminal-state errors. The only failures encountered during smoke runs were wrong expectations in my own test scripts (plus two self-inflicted server kills and one port collision with a sibling task's server) — no implementation defect was found.

## Step 5: Generate Unit Tests — 2026-08-13T11:38:00.000Z

All audits pass. The generation is complete.

## Summary

**Task**: `task_1455_foundry_casting_operations` — test infrastructure + suite generated purely from the two design indices against `workspace/PRD.md`.

**test_helpers/** (9 files, under `/home/ubuntu/github/CodingPRD/tasks/task_1455_foundry_casting_operations/test_helpers/`):
`__init__.py` (barrel), `types.py` (14 TypedDicts + 20 enums), `api_client.py` (45 endpoint methods), `api_errors.py` (35-error catalog registered via `set_error_http_status_map`), `assertions.py` (per-entity + alloy/sand mass invariant checkers), `factories.py`, `constants.py` (shrink factors, MA caps, 0.3mm tolerance, 0.85 yield, 500kg curtail threshold), `test_users.py` (opaque role constants incl. SoD probes `spectro_1`/`qi_1`/`wm_1`/`wm_2` + `make_customer_headers` for the entity-backed Customer role), `fixtures.py` (layered composites: `setup_shop` → `pour_molds` → `cool_and_shakeout` → `setup_casting_at_final_inspection` → `setup_fulfilled_order` → `setup_approved_claim`; OCC-threaded `add_charges`/`record_sample`/`run_ops`; Decimal-based `round_half_up`).

**test_suite/**: `conftest.py` + 10 numbered files, **98 tests**, all collecting under pytest.

**Coverage**
- Queue A (Difficulty): **36 tests / 18 instances** (≥2 each) — all generated.
- Queue B (Corner): **62 tests / 63 non-stub instances** (1 each).
- Stubs: 3 `cross_cutting_layers` `excluded_because` stubs not translated; all difficulty cross-references verified resolvable.

**Skipped instances (1)**
- `Corner/entities/pattern_create_extra_undeclared_field_rejected` — **not-uniquely-derivable**: PRD never states undeclared payload keys are rejected (ignoring them is equally PRD-faithful), so the asserted `ERR_INVALID_REQUEST` is not pinned.

**Notable construction decisions**
- `foundry_create_initializes_posture_embargo`: dropped the instance's `version == 1` assertion — PRD §2.5 never pins the initial version value (kept posture/sand/alloy/ops_run_index, all verbatim).
- `second_revision_activation_rejected`: dropped the instance's `qualification_attempts == 0` assertion — PRD contradicts it ("Each submission increments qualification_attempts by one"); kept the error + DRAFT assertions.
- `slot_complete_with_reclaiming_batch_rejected`: restructured setup with a second still-TAPPED heat — the literal recipe leaves heat1 POURED_OUT, which would mask the assertion with same-tier `ERR_HEAT_NOT_TAPPED`; the two-heat variant leaves `ERR_SAND_BATCH_INACTIVE` uniquely derivable.
- `order_fulfills_at_exact_quantity`: `fulfilled_at` asserted by timestamp prefix (millisecond rendering is only pinned for `created_at`/`updated_at`).
- Priority-pair tests (`settle_denied_claim_state_beats_budget`, `slot_complete_safety_beats_temporal`) rely on PRD §2.10's explicit cross-tier ordering — verbatim-cited.
- Final audits pass: every test has exactly one resolving `Design:` tag as the docstring's last line; every quoted citation greps verbatim against PRD.md; no skip/xfail markers; no scaffold references in generated code.

## Step 7: Run Tests and Iterate — 2026-08-13T12:12:00.000Z

All 8 parallel rounds pass 98/98. The task is complete.

## Summary

**Iterations run:** 2 (sweep 1: 4 tests failing deterministically in all 8 rounds; sweep 2 after fixes: all 8 rounds clean, 98/98 each, zero flakiness observed).

**Tests deleted:** none.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1455_foundry_casting_operations/workspace/implementation/db.py` (`new_record`) — minted resource ids as `uuid.uuid4().hex` (dashless); changed to `str(uuid.uuid4())` so ids are canonical hyphenated UUIDs per PRD §2.5 ("`id` is a server-minted UUID with no type prefix"). This fixed both `test_foundry_create_initializes_posture_embargo` and `test_provisional_credit_at_disposition`, whose `assert_foundry`/`assert_scrap_record` helpers correctly validate UUID format.

**Fixes applied to `test_suite/`:**
- `test_02_pattern_tooling.py::test_second_revision_activation_rejected` — reordered the setup: `pat_c` is now created while sibling `pat_b` is still DRAFT (creation is legal per PRD §3.2, which rejects creation only when the parent "already has an `ACTIVE` child revision"), then `pat_b` qualifies (superseding the parent), then `pat_c`'s qualification correctly draws `ERR_ACTIVE_REVISION_EXISTS` from the activation-time guard the test's PRD quote actually targets. Previously the test created `pat_c` after `pat_b` activated, so the PRD-mandated creation-time guard (rightly implemented) rejected it with 409 where the test wrongly expected 201.
- `test_05_ops_epoch_and_occ.py::test_occ_sample_with_stale_heat_version_rejected` — restructured the scenario to eliminate an ERROR PRECEDENCE SILENCE: the heat previously ended CERTIFIED, so §2.10 tier-4 state feasibility ("Sampling is accepted only while the heat is `CHARGING` or `SAMPLED`" → `ERR_INVALID_STATE`) legitimately fired before the OCC check, and §2.10 never places `ERR_STALE_VERSION` in the priority chain. The first sample now deliberately fails (reading 4.50 &gt; spec max 3.6) leaving the heat SAMPLED — a legal sampling state — so the stale-version second sample can only be rejected with `ERR_STALE_VERSION` (§2.6). Exact error_id assertion preserved; side-effect assertion updated to the failing reading (4.50).

**Fixes applied to `test_helpers/`:** none needed (helpers were PRD-faithful; the triage hint about a shared fixture bug did not apply — the 4 failures had 3 distinct root causes).

**Orchestrator verification:** Step 7 subagent cleaned up its results files on exit; orchestrator re-ran the full 8-round parallel sweep independently — all 8 rounds 98/98, 0 failed. `results.{1..8}.json` regenerated under `workspace/implementation/`.

## Step 8: Finalize PRD — 2026-08-13T12:20:00.000Z

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1455_foundry_casting_operations/workspace/PRD_FINALIZED.md`.

## Summary

**Line counts / delta:** PRD.md = 326 lines, PRD_FINALIZED.md = 328 lines (+2 lines, +0.61%). Exactly one edit; `diff` confirms a pure insertion with zero other drift.

### Disposition of each step_7_diff item

- **Item 1 (UUID fix, `db.py::new_record`)** — No PRD edit. This was an implementation fix *toward* the PRD: §2.5 already pins "`id` is a server-minted UUID with no type prefix," and the runner's `is_valid_uuid` (prd-bench-local-runner/src/prd_bench_local_runner/testing/assertions.py:19-25) regex requires the canonical hyphenated 8-4-4-4-12 form. PRD already determined the behavior; prose kept verbatim.

- **Item 2 (pattern revision test reorder)** — No PRD edit. Pure test-fixture bug. PRD §3.2 already pins both guards distinctly: creation-time ("If the named parent already has an `ACTIVE` child revision, creation is rejected with `ERR_ACTIVE_REVISION_EXISTS`", PRD_FINALIZED.md:137) and qualification/activation-time ("Activation carries two uniqueness guards, both raising `ERR_ACTIVE_REVISION_EXISTS`...", PRD_FINALIZED.md:143). Implementation matches both exactly (implementation/routes/patterns.py:59-62 creation guard; :134-147 activation guards), so the PRD was not ambiguous about which guard fires when.

- **Item 3 (OCC vs. state-check precedence)** — Genuine PRD silence; one edit made.

### Change bullet

- **§2.10 — insert — appended a paragraph placing the §2.6 optimistic-concurrency version comparison after every other precondition (authn, authz, existence, payload shape including the version field itself, state feasibility, business guards), with `ERR_STALE_VERSION` returned only when the expected version is present, well-formed, unequal to current `version`, and nothing else fails — implementation/routes/heats.py:154 and :203 (OCC is the last precondition before mutation on charges and samples), implementation/routes/foundries.py:47-50 (OCC is the only business check after auth/role/existence on run-ops), implementation/util.py:93-113 (missing/non-integer version field → `ERR_INVALID_REQUEST` before any comparison).**

### Per-edit pre-edit search log (NO-NEW-MISMATCH rule)

- (a) **Subject:** relative priority of the optimistic-concurrency version check (`ERR_STALE_VERSION`) against all other request validations, on every OCC-guarded endpoint.
- (b) **Paths enumerated and read:** `grep -rn "STALE_VERSION|expected_heat_version|expected_foundry_version|_check_occ" implementation/` → three guarded operations only: `POST /api/heats/{id}/charges` (implementation/routes/heats.py:94-184 — auth → role → heat 404 → mode/additions shape → state feasibility :108-113 → per-addition shape/source/composition :117-141 → return-lot existence/cross-foundry :138-140 → `ERR_RETURN_LOT_NOT_ASSAYED`/`ERR_RETURN_LOT_INSUFFICIENT` :144-151 → `_check_occ` :154, then mutation); `POST /api/heats/{id}/samples` (heats.py:186-214 — auth → role → 404 → reading shape :192-194 → terminal/state/empty-bath :196-201 → `_check_occ` :203, then mutation); `POST /api/foundries/{id}/run-ops` (implementation/routes/foundries.py:39-52 — auth → role → 404 → `req`+`as_int` on the version field → comparison; the sweep itself never fails). Also read implementation/util.py:93-113 (`req`/`as_int` raise `ERR_INVALID_REQUEST` for absent/non-integer version fields *before* any comparison) and implementation/errors.py:21 (412 mapping, already in PRD §5). No other endpoint takes a version field (consistent with §2.6's "no other endpoint takes a version field").
- (c) **Wording adjustment:** initial draft considered saying the check runs "last in the priority chain"; widened to "evaluated after every other precondition of the request — authentication, authorization, existence, payload shape (including the presence and integer type of the expected-version field itself), state feasibility, and the business guards above" so it (i) covers the run-ops endpoint, where the OCC comparison follows field-shape validation but precedes no other business check, (ii) covers the charges endpoint, where `ERR_INVALID_REQUEST` shape checks both precede and interleave with state/existence checks, and (iii) avoids claiming a fixed chain position that no single endpoint's code literally exhibits. The "business guards above" phrase scopes to the same §2.10 tiers without reordering them.

## Step 9: Complete PRD — 2026-08-13T12:35:00.000Z

(Orchestrator note: the Step 9 subagent's first pass completed its exhaustive implementation walk but exited before applying its catalogued edits — PRD_COMPLETED.md was byte-identical to PRD_FINALIZED.md. The subagent was resumed with its analysis context intact and applied all edits on the second pass. Final summary below.)

## Exit Summary

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_1455_foundry_casting_operations/workspace/PRD_COMPLETED.md`
**Source**: `PRD_FINALIZED.md` (328 lines, 57,723 chars) → `PRD_COMPLETED.md` (328 lines, 60,960 chars). Char delta: **+3,237**; line count unchanged (all edits in-paragraph, per method).

**Counts**: 18 ambiguity-pins, 2 mismatch-revisions (20 edits total).

### Ambiguity-pins (insert)

- §2.1 — insert — ambiguity — Customer list results silently restricted to owned records (no error) — implementation/routes/orders.py:84-85, implementation/routes/claims.py:90-91
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` → ERR_INVALID_REQUEST; out-of-range values clamped (limit→[1,100], offset→0) — implementation/middleware.py:43-56
- §2.4 — insert — ambiguity — clock-set capability returns HTTP 200 with object carrying `current_utc` — implementation/routes/clock.py:19
- §2.5 — insert — ambiguity — `version` starts at 1 on creation — implementation/db.py:51
- §3.1 — insert — ambiguity — `credit_limit_cents` must be a non-negative integer or ERR_INVALID_REQUEST — implementation/routes/customers.py:20-22
- §3.1 — insert — ambiguity — window-add endpoint returns HTTP 201 with the updated equipment record — implementation/routes/equipment.py:101
- §3.2 — insert — ambiguity — `finish_dimensions_mm` entries and `machining_allowance_mm` must be non-negative numbers — implementation/routes/patterns.py:43-45
- §3.2 — insert — ambiguity — same-`part_number` ACTIVE guard scoped to same foundry, parent exempt — implementation/routes/patterns.py:140-147
- §3.3 — insert — ambiguity — order field types/signs (quantity positive int; unit_price/warranty_months/budget non-neg ints; pcts non-neg numbers); pattern status unchecked at placement — implementation/routes/orders.py:24-29, 41-43
- §3.4 — insert — ambiguity — charge `weight_kg` zero-or-greater; virgin `composition` may be omitted (contributes no elements) — implementation/routes/heats.py:125-131
- §3.4 — insert — ambiguity — `mode` must be exactly `AUTO_CORRECT` when present; AUTO_CORRECT applies only computed masses, `additions` ignored — implementation/routes/heats.py:100-102, 117, 157-164
- §3.4 — insert — ambiguity — `tap_weight_kg` must be zero or greater — implementation/routes/heats.py:222
- §3.5 — insert — ambiguity — mold `sand_weight_kg`/`metal_weight_kg` zero-or-greater, `cooling_hours` non-neg int; order status not a mold-creation precondition — implementation/routes/molds.py:25-32
- §3.5 — insert — ambiguity — `mold_ids` must be non-empty array; heat state unconstrained at booking (TAPPED binds at completion) — implementation/routes/pour_slots.py:35-37, 46-48
- §3.6 — insert — ambiguity — SCRAP also requires `return_lot_id` (absence → ERR_INVALID_REQUEST); lot credited regardless of its status — implementation/routes/inspections.py:128-133, 166-169
- §3.7 — insert — ambiguity — assay: spec element absent from `assay_composition` fails; `ce_max` plays no role in lot assay — implementation/routes/return_lots.py:17-32, implementation/services.py:193-199
- §3.7 — insert — ambiguity — `collected_weight_kg` must be zero or greater — implementation/routes/return_lots.py:43
- §3.8 — insert — ambiguity — `virgin_weight_kg` and `max_loi_pct` must be zero or greater — implementation/routes/sand.py:24-25
- §3.9 — insert — ambiguity — claim field validation (claim_qty positive int; claimed_amount_cents/freight_cents non-neg ints); window end computed by calendar-month addition with day clamped to month length; filing exactly at window end passes — implementation/routes/claims.py:37-39, 51-54, implementation/util.py:73-78
- §3.9 — insert — ambiguity — review `note` accepted but not persisted — implementation/routes/claims.py (note never read)

### Mismatch-revisions (revise)

- §3.1 — revise — mismatch — PRD said MOLDING_LINE `cleanup_buffer_minutes` is "mandatory" and implied capacities always present; impl makes all three capacity/buffer fields optional (null tap capacity = uncapped, null minute capacity = uncapped, null buffer = treated as 0), with type validation when supplied — implementation/routes/equipment.py:23-32, implementation/routes/heats.py:239, implementation/routes/pour_slots.py:68, 82
- §3.5 — revise — mismatch — PRD said line daily tally uses "whole-minute durations ... on the same UTC date"; impl uses exact second-precision durations and keys the daily tally to each slot's UTC start date — implementation/routes/pour_slots.py:83-91

