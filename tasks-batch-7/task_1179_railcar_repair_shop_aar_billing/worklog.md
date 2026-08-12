# Worklog — task_1179_railcar_repair_shop_aar_billing

## Step 1: Create task directory — 2026-08-11T11:57:00.000Z

Task directory pre-assigned by orchestrator invocation: `tasks/task_1179_railcar_repair_shop_aar_billing/` with `workspace/` subdirectory already existing. Auto-index scan skipped per instructions. Step 1 treated as done.

## Step 2: Generate Scaffold — 2026-08-11T13:21:00.000Z

Generated the complete scaffold for **task 1179 — Railcar Repair Shop & AAR Billing** at beyond-expert depth, purely from the scenario + skill spec (no sibling tasks consulted).

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1179_railcar_repair_shop_aar_billing/SCAFFOLD.yaml` (102 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_1179_railcar_repair_shop_aar_billing/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (114 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_1179_railcar_repair_shop_aar_billing/SCAFFOLD_CORNER_DESIGN.yaml` (145 KB)

**Counts:**
- Entities: **16** (Shop, CarOwner, HandlingLine, Railcar, Inspection, DefectFinding, WorkOrder, RepairLine, PriceMasterEntry, PartItem, Wheelset, ShopSlot, BillingRepairCard, BrcLine, CounterBill, WarrantyClaim)
- State machines: **11 blocks / 61 transitions** — WorkOrder runs parallel axes (auth_status × exec_status) with a QA rework cycle; BRC has a SUBMITTED⇄DISPUTED counter-billing cycle; Inspection reopen, Wheelset reclaim, CounterBill rebut/revise, and WarrantyClaim appeal cycles on top
- Calculations: **10** (estimate vs final pricing across rate windows, decision-table responsibility R1–R6, dual-variant dwell, pinned per-line-rounding BRC aggregation, 60% counter ceiling, order-pinned warranty credit, capacity posture, wheelset condemnation, parts availability invariant)
- Endpoints: **81** (48 POST actions/creates, 33 GETs incl. all FK reverse-reachability), plus `/_clock/set_current_utc` with the mandated 2026-05-01T00:00:00Z default
- Errors: **36**; Validations: **14** priority tiers; Roles: **10** (segregation-of-duties: QA reviewer ≠ WO creator; rule-determined authorizer party); Concurrency rules: **4** true OCC races (WO create / authorize / revise-estimate / BRC create), all with `expected_*_version` inputs and parent version bumps
- Difficulty instances: **19** (all 9 rules ≥ 2; combinatorial_formula carries 3 — one per mode a/b/c), every assert literal pre-computed (e.g., rounding chain 3000+3000=6000 vs forbidden 5999; dwell 48.0h→0c; counter cap exactly 3600 allowed, 3601 rejected)
- Corner instances: **42 active + 1 excluded stub** across all nine claim-guide sections

**Verification:** `scaffold_lint.py` verdict — **clean lint** (1000 recipe calls checked against §1.5, zero violations, all FKs reverse-reachable). Additional scripted audits passed: no forbidden concurrency vocabulary, correct file key separation, 62 unique instance names, all `grounds` refs resolve, every error code is referenced and declared, OCC hard constraints hold, and two replay bugs I caught (counter after BRC-acceptance; empty setup chain) were fixed by reordering recipes.

One notable design adaptation: the lint's FK/segment derivation requires flat root collections with `{id}` placeholders, so the API uses flat paths (`/work-orders/{id}`, `/billing-repair-cards/{id}/counter-bills`) with `shop_id` body/query scoping instead of shop-nested paths; `api_prefix` is `""` accordingly.

## Step 3: Copy shared files — 2026-08-11T13:23:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1179_railcar_repair_shop_aar_billing/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-11T13:35:00.000Z

PRD generated and verified at `/home/ubuntu/github/CodingPRD/tasks/task_1179_railcar_repair_shop_aar_billing/workspace/PRD.md` (361 lines, ~59 KB). The withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, nor was any other `task_*` directory.

**Section list**

- **§1. Introduction** (2 paragraphs, business-context angle: provisional-vs-final reconciliation and counter-billing as first-class domain forces)
- **§2. Global Specifications** — 2.1 RBAC & identity semantics · 2.2 API Response Structure (**byte-identical verbatim block, diff-verified**) · 2.3 Pagination · 2.4 Logical Clock & Sweep · 2.5 Capacity Posture & Intake Gating · 2.6 Price Master Effective Dating · 2.7 Provisional vs Final Pricing · 2.8 AAR Responsibility Determination · 2.9 Parts Inventory Invariants · 2.10 Party Ledgers & Credit Watch · 2.11 Common Properties & OCC · 2.12 Validation Order & Nested Retrieval
- **§3. Business Logic** — 9 subsections organized on the business timeline: shop setup → inbound/inspection → work-order build/estimate → authorization → routing/execution/QA gate → departure/dwell/wheelsets → BRC lifecycle → counter-bill cycle → warranty/appeals
- **§4. Endpoint Definitions** — 81 endpoints, strict 4-column table (83 rows incl. header/separator)
- **§5. Error Code Catalogue** — 36 errors, strict 2-column table

**Hard Contract reports**

- **Contract 1 (Field-Name Coverage):** entity fields 110 required / 110 present / 0 missing; endpoint-only identifiers (`to_iso8601`, `expected_railcar_version`, `line_actuals`, `brc_line_id`, `counter_amount_cents`, dwell-summary outputs, etc.) 19 required / 19 present / 0 missing; all query-param names present — **PASS**
- **Contract 2 (Rule Coverage):** all 14 validation priorities expressed as an ordered ladder in §2.12 plus intra-endpoint orderings (counter ceilings: aggregate 60% cap before per-line remainder; sweep: expiry before deemed acceptance); 4/4 OCC rules named with endpoint + `expected_<parent>_version` + exact error id + 412, no race-framing; all ~40 state transitions with preconditions/side effects; all 10 calculations as reconstruction-test prose (responsibility decision table R1–R6 with 24h/3-decimal window, dwell actual vs projected variants with the no-delay-subtraction asymmetry, BRC aggregation rounding order, counter floor(0.60×) cap with equality allowed, warranty min-cap with evaluation order, capacity 85%/FULL boundary, wheelset 28.0/9.5 boundaries, parts reserve/consume/release/adjust); all `applies_to` scopes and cascades enumerated; sibling branches (QA PASS/FAIL, cancel DRAFT/AUTHORIZED, depart ARRIVED/READY) at equal density — **PASS**
- **Contract 3 (§3 Path Purity):** 564 backtick tokens scanned; 0 path tokens, 0 bare HTTP methods, 0 method+path combos — **PASS**

**Zero-Silence-Rule adjudications**

1. **Superseded draft work order** — scaffold's create side effects specify only `auth_status`/`exec_status` → `CANCELLED` for the superseded draft; I mirrored exactly that and did not invent line/finding compensation for it.
2. **"Owner share of accepted counter credits"** at BRC accept/settle — scaffold gives no per-credit split formula, only net posting; I kept the net-posting phrasing without inventing rounding.
3. **Dwell-summary live read** — scaffold says "recomputes actual live" without pinning the end instant for non-departed cars; the PRD says "recomputes the actual variant live at read time" without over-specifying.
4. **`READY_FOR_DEPARTURE` → `DEPARTED` asymmetry** — scaffold lists only the safety gate for that branch (no open-WO check); preserved as-is.
5. **Railcar `(reporting_mark, car_number)` uniqueness** — declared in the entity table but with no catalog error; stated as a constraint with no error ID attached.

## Step 5: Generate Unit Tests — 2026-08-11T14:19:00.000Z

Generation complete and verified. Summary:

**Files generated**

**`test_helpers/`** (all 9 required modules):
- `types.py` — 16 entity TypedDicts (all carry common fields per the PRD), 19 status/enum vocabularies, `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (clock, shops, owners, lines, price master, parts, wheelsets, slots, railcars, inspections/defects, work orders/lines, BRCs/brc-lines, counter-bills, warranty claims)
- `api_errors.py` — `ApiErrorId` (36 ids) + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + `assert_part_quantity_invariant` (available == on_hand − reserved) + `assert_brc_money_conservation` (net == submitted − credits; owner + handling == submitted)
- `factories.py`, `constants.py` (clock pins, shop defaults, 24h interchange window, 0.85 ratio, 0.60 cap, 28.0/9.5 wheelset limits), `test_users.py` (opaque-role constants + mandatory per-instance builders for entity-backed `CarOwnerRep`/`HandlingLineRep`), `fixtures.py` (5 tiers: atomic builders → `setup_shop_ctx` → `add_car_with_inspection` → WO lifecycle chain with OCC auto-refetch and party-resolving authorize → BRC lifecycle; `scenario_authorized_wo`/`scenario_completed_wo`/`scenario_submitted_brc` composites), `__init__.py` barrel

**`test_suite/`**: `conftest.py` + 26 test files, **80 test functions total**.

**Test counts by queue**
- **Queue A (Difficulty): 38 tests** — all 19 instances × exactly 2 tests each, tags `Design: Difficulty/<rule_id>/<instance>`
- **Queue B (Corner): 42 tests** — all 42 non-stub instances × 1 test each, tags `Design: Corner/<section>/<instance>`
- **Stubs not translated: 1** — `Corner/state_machines/qa_rework_loop_covered_by_difficulty` (cross-reference to `non_linear_state_machine/work_order_parallel_axes_with_qa_rework_cycle` verified resolvable)

**PRD-first filter skips**
**None.** Every one of the 61 non-stub instances has verbatim PRD coverage and uniquely-derived outcomes. One borderline was adjudicated and kept: `responsibility_shared_split_precedes_wear_group`'s `owner_share_pct == 50` assertion — PRD §2.8's "owner-responsible share of the estimate total" converges with §3.7's per-line owner-share money math (50% of 6000), so both readers land on 50.

**Lint / verification results**
- `python3 -m py_compile` over both directories: clean
- `pytest --collect-only`: 80 tests collected, no import errors
- AST-based audit (custom script): every test docstring carries exactly one `Design:` tag as its final line; all 80 tags resolve to real YAML instances; difficulty coverage 38/38, corner 42/42
- Verbatim-citation grep: every `PRD §x.y: "..."` quote in all 80 docstrings survives literal substring match against `workspace/PRD.md` (4 initially-elided quotes were rewritten to full-sentence form and re-verified)
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no "scaffold"/table references in generated code

One design note: timestamp equality assertions parse ISO-8601 to instants rather than comparing strings, since PRD §2.11's "three fractional digits" rendering leaves `...T08:00:00Z` vs `...T08:00:00.000Z` open — instant comparison is the uniquely-derivable assertion.

## Step 6: Generate Implementation — 2026-08-11T14:19:30.000Z

Implementation complete and verified. Summary:

**Files (all under `workspace/implementation/`)**

- `start.sh` — executable; guarded dependency install (`import flask` check, no re-install on per-test reboots); `exec python3 app.py` in foreground; binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=2.2`
- `app.py` — Flask entry point, blueprint registration, envelope error handlers (404/405/ApiError/catch-all), global request lock
- `db.py` — in-memory `STORE` dicts (16 collections) + logical clock (starts exactly `2026-05-01T00:00:00Z`, never wall-clock)
- `errors.py` — `ApiError(error_id, status, message)`
- `common.py` — ISO-8601 3-fractional-digit timestamps, `meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more` pagination, X-User-ID/X-User-Role auth decorator (9 declared roles + `Any`), validation helpers, and all calculation primitives (Decimal, ROUND_HALF_UP)
- `billing_ops.py` — BRC net-settled recompute, party-balance net posting, dispute resolution cascade, responsibility party-match
- `routes_core.py` — clock, shops (+sweep with counter expiry then deemed acceptance), car-owners, handling-lines, price-master (closed-window overlap), parts (+adjust), wheelsets (mount/remove/evaluate with 28.0/9.5 condemn boundaries), shop-slots (+block)
- `routes_rail.py` — railcars (+depart with open-WO and condemnable-defect gates, dwell actual), dwell-summary (live recompute), inspections (complete/reopen with lock), defects (AAR-NNNN validation, decline)
- `routes_wo.py` — work orders (OCC on railcar version, draft supersession, capacity intake gate), lines (estimate pricing), submit (responsibility decision table R1–R6, majority by estimate sums, tie → OWNER), authorize (OCC + party match + atomic parts reservation), reject, revise-estimate, assign-slot (half-open overlap, window-vs-standard-hours), dispatch, start, complete (line_actuals coverage), qa-review (SoD, final pricing, parts consume, slot release, sibling-ready cascade, rework loop with QA-delay accrual), cancel (compensating releases)
- `routes_billing.py` — BRCs (draft with FINALIZED-line snapshots, supersession, pinned totals, mobile surcharge to majority party), submit/accept/withdraw/settle, counter-bills (aggregate 60% floor cap before per-line remaining, rebut/revise/withdraw cycles, window enforcement), warranty claims (window/group/active eligibility, credit = min(remaining, claimed), party-split balance credits, appeals)

**Verification results**

- **Route inventory**: exactly **81 registered (method, path) pairs vs 81 scaffold endpoints** — 0 missing, 0 extra (verified programmatically against `SCAFFOLD.yaml` via Flask's url_map)
- **py_compile**: passes on all 9 `.py` files
- **Smoke test** (harness-style): fresh `PORT=<free> bash start.sh` boot → 404 route returns the `ERR_NOT_FOUND` envelope, list endpoint returns empty state (`total_count: 0`) confirming no seeding; process kills cleanly
- **Storage**: in-memory only — grep confirms no sqlite/file/json-dump/open calls and no seed/preload code; store starts empty every boot
- **Functional**: 4 E2E suites (~120 assertions) all pass on fresh boots, covering the full lifecycle, OCC staleness (railcar + work-order), SoD, RBAC/party/filer mismatches, price windows, estimate-vs-final dual pricing with mobile rate, dwell projected/actual/boundary cases, posture FULL intake gating, slot overlap/adjacency, credit-watch flip, counter ceilings and dispute cycles, sweep expiry + deemed acceptance, warranty honor/appeal/expiry, and error-catalog paths (400/403/404/409/412/422)

Two ambiguity calls worth noting: `ERR_COUNTER_BILL_ACTIVE` (not `ERR_INVALID_STATE_TRANSITION`) is returned when accepting/withdrawing a `DISPUTED` card with an active counter — per PRD §3.7's explicit mapping and the error catalog; and a `REMOVED`/`IN_STOCK` wheelset evaluated within limits reclaims/stays `IN_STOCK` while evaluations from `MOUNTED`/`CONDEMNED` are rejected as invalid transitions.

## Step 7: Run tests and iterate — 2026-08-11T14:36:00.000Z

Clean 8-round parallel sweep achieved: **80/80 passed in every round, 0 failed, 0 skipped.** (Orchestrator independently verified all 8 `results.{i}.json` files on disk: passed=80 total=80 failed=0 skipped=0 for rounds 1–8.)

**Iterations run:** 2 (sweep 1: 66/80 × 8 rounds; sweep 2 after fixes: 80/80 × 8 rounds)

**Tests deleted:** None. Every failing test traced to verbatim PRD prose; all fixes were faithful-direction.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1179_railcar_repair_shop_aar_billing/test_suite/test_21_transitive_cascades.py` — added the missing `authorize_current_wo` import. 4 tests (`test_authorize_cascades_line_status_and_reservation`, `test_authorize_reservation_flips_part_to_reorder_needed`, `test_counter_accept_cascades_credit_and_net`, `test_counter_accept_returns_brc_to_submitted`) called it at lines 41/61/88 but the module's import list omitted it → NameError.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1179_railcar_repair_shop_aar_billing/test_helpers/factories.py` — `line_actual()` sent the wire field `parts_used`; PRD §3.5 ("records each line's `actual_labor_hours` and `actual_parts`") and §2.7 ("sum, over `actual_parts`") verbatim name it `actual_parts`. The implementation correctly ignored the unknown key, so no material was priced and no stock consumed — the single root cause behind 8 deterministic failures (BRC totals of 18000 vs expected 22500 = labor+material, counter/warranty/settlement nets, part-depleted flip, mobile surcharge card).

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1179_railcar_repair_shop_aar_billing/workspace/implementation/common.py` — `compute_wo_responsibility()` computed `owner_share_pct` from the majority aggregate (full estimate of lines with `owner_pct ≥ 50`); PRD §2.8 defines it as "the owner-responsible share of the estimate total". Now weights each line by `estimate_total × owner_pct / 100` (single SHARED-50 line of 6000 → 50, was 100).
- `/home/ubuntu/github/CodingPRD/tasks/task_1179_railcar_repair_shop_aar_billing/workspace/implementation/start.sh` — replaced the per-boot `python3 -c "import flask"` dependency probe (a full interpreter+Flask import on every per-test server restart) with a `.deps_installed` sentinel; boot 468ms → 370ms. This addressed the 2 infra-flaky failures (`test_slot_overlap_beats_window_too_short_on_assign`, `test_rejected_assign_leaves_order_and_slot_untouched`) whose restart timeouts correlated with CPU contention from other task pipelines running on the shared host.

**Route check:** 81/81 scaffold endpoints registered (verified programmatically via Flask url_map; sole extra is Flask's built-in `/static/`).

## Step 8: Finalize PRD — 2026-08-11T14:43:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1179_railcar_repair_shop_aar_billing/workspace/PRD_FINALIZED.md` written with exactly one edit.

**Line counts / %-delta**
- PRD.md: 361 lines; PRD_FINALIZED.md: 361 lines — 0.0% delta (single in-place sentence revision on line 113, no lines added or removed).

**Changes**
- **§2.8 — revise —** Replaced the ambiguous "`owner_share_pct` … otherwise the owner-responsible share of the estimate total" with the pinned per-line-weighted formula: each line contributes `estimate_total_cents × owner_pct / 100` rounded half up to whole cents; `owner_share_pct` is that sum as a percentage of the work order's `estimate_total_cents`, rounded half up to a whole percent, explicitly "computed per line rather than by the majority aggregate above"; added the zero-estimate-total guard (`owner_share_pct` is 100). — `implementation/common.py:434-452` (`compute_wo_responsibility`, sole writer callsite `implementation/routes_wo.py:273-275`).

**Items reviewed with no PRD edit (with reasons)**
- `test_suite/test_21_transitive_cascades.py` import fix — pure test-side NameError; no PRD bearing.
- `test_helpers/factories.py` `line_actual()` fix — verified PRD already pins the wire field uniquely: `actual_parts` appears verbatim in §2.7 ("sum, over `actual_parts`") and §3.5 ("records each line's `actual_labor_hours` and `actual_parts`"), and the impl reads exactly that key (`implementation/routes_wo.py:501`). PRD was right; test was wrong.
- `implementation/start.sh` sentinel — infra boot optimization; PRD is silent on process startup and stays so.

**Per-edit pre-edit search log (NO-NEW-MISMATCH RULE)**

**Edit 1 (§2.8 `owner_share_pct` sentence):**
- (a) Subject: work-order-level `owner_share_pct` computation (estimate-split summary at submission).
- (b) Enumerated impl paths touching the subject, all read/grepped: `implementation/common.py:434-452` (definition — per-line `rhu_cents(est × pct / 100)`, summed, then `rhu_cents(owner_money × 100 / total)`; `total == 0` → 100); `implementation/routes_wo.py:273-275` (only writer callsite, at submit) and `routes_wo.py:120` (init `None` at creation); full-repo grep for readers of `owner_share_pct` returned none — BRC owner totals (`implementation/routes_billing.py:91-92`), counter-credit party shares (`implementation/billing_ops.py:34-45`), and warranty credit splits (`implementation/routes_billing.py:566-568`) all use per-line `owner_pct` directly on final amounts/credits and never read `owner_share_pct`. PRD cross-references checked: §3.3's "sets … `owner_share_pct` from the estimate sums" is consistent; §2.10's "owner-responsible share of accepted counter-bill credits" is a different quantity the edit does not touch.
- (c) Wording adjustments: (i) scoped the formula to the estimate split and added "computed per line rather than by the majority aggregate above" so it coexists without contradiction with the adjacent `responsible_party` majority-aggregate rule, which the impl still uses (`common.py:439-441`); (ii) kept the original 100/0 endpoints as formula consequences ("yielding 100 when every line is owner-responsible and 0 when none is") rather than independent rules, since the decision table only produces `owner_pct` ∈ {0, 50, 100} making both endpoints exact; (iii) added the zero-total guard clause matching `common.py:442-443` exactly; (iv) mirrored §3.7's established per-line half-up rounding phrasing for consistency with the BRC `owner_share_cents` rule.

## Step 7: Stability sweep fix loop — 2026-08-11T14:36:00.000Z

Iteration 1 sweep: 66/80 in all 8 rounds. Union of failures: 15 tests (13 deterministic, 2 infra-flaky).

Fixes applied:

1. `test_suite/test_21_transitive_cascades.py` — added missing `authorize_current_wo` import (4 tests failed with NameError at call time; the name was defined in test_helpers/fixtures.py and exported via the barrel, but never imported into this test module).

2. `test_helpers/factories.py` `line_actual()` — wire field was `parts_used`; PRD §2.7/§3.5 verbatim name the completion-recorded field `actual_parts` ("records each line's `actual_labor_hours` and `actual_parts`"; "sum, over `actual_parts`"). The implementation correctly ignored the unknown key, so material was never priced and stock never consumed — root cause of 8 deterministic failures (mobile surcharge BRC totals, credit-watch flip, counter accept/file/withdraw nets, honored-credit remainder, net-posting conservation, settlement drift, part-depleted flip).

3. `workspace/implementation/common.py` `compute_wo_responsibility()` — `owner_share_pct` was computed from the majority aggregate (full estimate of lines with owner_pct>=50); PRD §2.8 defines it as "the owner-responsible share of the estimate total", i.e. sum(estimate_total x owner_pct/100) / total. Single SHARED-50 line of 6000: 50, not 100.

4. `workspace/implementation/start.sh` — replaced per-boot `python3 -c "import flask"` probe (a full interpreter+flask import per server boot) with a `.deps_installed` sentinel check; boot 468ms -> 370ms. Addresses the 2 infra-flaky "could not be restarted" / ConnectionReset failures under 8x parallel load on a shared host (other task pipelines running concurrently).

Iteration 2 sweep: 80/80 in all 8 rounds, 0 failed, 0 skipped. No tests deleted; no assertions weakened.

## Step 9: Complete PRD — 2026-08-11T14:57:00.000Z

Done. `PRD_COMPLETED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1179_railcar_repair_shop_aar_billing/workspace/PRD_COMPLETED.md`.

**Files**: PRD_FINALIZED.md — 361 lines / 59,416 chars; PRD_COMPLETED.md — 361 lines / 61,777 chars (**+2,361 chars**, 21 paragraphs touched, no sections added).

**Counts**: 19 ambiguity-pins, 4 mismatch-revisions (one edit, §2.9, contains both an ambiguity insert and a mismatch revise; counted once in each).

**Changes** (section — insert|revise — ambiguity|mismatch — what changed — impl anchor):

- §2.3 — insert — ambiguity — invalid `limit`/`offset` rejected with `ERR_INVALID_REQUEST`; `created_at` ties broken by creation order; `has_more` defined as `offset + limit < total_count` — common.py:257-281, 253-254
- §2.6 — insert — ambiguity — inverted price window (`effective_to` < `effective_from`) rejected with `ERR_INVALID_REQUEST` — routes_core.py:210-211
- §2.9 — insert+revise — ambiguity+mismatch — zero `delta_qty` rejected with `ERR_INVALID_REQUEST`; adjustment "requires" (not "records") a `reason` since impl never persists it — routes_core.py:306-309
- §2.11 — revise — ambiguity — `version` pinned to start at 1 on creation — common.py:223-226
- §2.12 — revise — mismatch — validation order resequenced: path existence (now 3rd) and body references (now 4th) precede party/filer checks (5th) and segregation of duties (6th); impl resolves path/body resources before party/SoD checks in every handler — routes_wo.py:284-286, 538-542; routes_billing.py:316-321
- §2.12 — insert — ambiguity — undefined path or unsupported method → `ERR_NOT_FOUND` (404); body reference belonging to a different parent (inspection of another railcar, finding of another inspection, card line of another card) → `ERR_REFERENCE_NOT_FOUND` — app.py:47-58; routes_wo.py:87-89, 160-162; routes_billing.py:268-271
- §3.2 — revise — mismatch — dropped the unenforced "(reporting_mark, car_number) is unique within the shop" claim; impl performs no duplicate check — routes_rail.py:36-64
- §3.3 — insert — ambiguity — draft supersession on WO create also cancels the old draft's lines and returns their findings to `OPEN` — routes_wo.py:104-110
- §3.3 — insert — ambiguity — adding a line requires the referenced finding to be `OPEN`, else `ERR_INVALID_STATE_TRANSITION` — routes_wo.py:179-181
- §3.4 — insert — ambiguity — revise-estimate recomputes only estimate money; line and work-order responsibility fields are not re-decided — routes_wo.py:365-373
- §3.4 — insert — ambiguity — reject `reason` accepted but not persisted — routes_wo.py:330
- §3.5 — revise — ambiguity — `line_actuals` entry shape pinned: `repair_line_id` key, non-negative `actual_labor_hours`, optional `actual_parts`; duplicates/cancelled-line references rejected with `ERR_INVALID_REQUEST` — routes_wo.py:477-515
- §3.5 — insert — ambiguity — QA `result` matched case-insensitively; `notes` accepted but not persisted — routes_wo.py:546-549
- §3.5 — insert — ambiguity — cancel `reason` not persisted; cancellation leaves a pinned `projected_dwell_charge_cents` unchanged — routes_wo.py:610-621
- §3.6 — revise — mismatch — `ERR_OPEN_WORK_ORDERS` guard applies from both `ARRIVED` and `READY_FOR_DEPARTURE` (PRD said "From ARRIVED" only) — routes_rail.py:89-97
- §3.6 — insert — ambiguity — dwell summary measures through `departed_at` for a departed car, else the current logical time — routes_rail.py:120
- §3.6 — insert — ambiguity — an `IN_STOCK` wheelset evaluated inside both limits remains `IN_STOCK` — routes_core.py:426-427
- §3.7 — insert — ambiguity — BRC submission re-verifies the billed work order is still `COMPLETED` (`ERR_WORK_ORDER_NOT_COMPLETED`) — routes_billing.py:179-182
- §3.8 — insert — ambiguity — `rebuttal_note` accepted but not persisted — routes_billing.py:393
- §3.8 — insert — ambiguity — counter revision excludes the bill's own previous total from the running aggregate; replacement-item references and ceilings validated only after the window check — routes_billing.py:418-423
- §3.9 — insert — ambiguity — deny `reason` accepted but not persisted — routes_billing.py:531
- §3.9 — insert — ambiguity — honored warranty credit lands on the latest-created card line of a non-superseded card (latest overall if all superseded) — routes_billing.py:552-560
- §3.9 — insert — ambiguity — appeal `note` accepted but not persisted — routes_billing.py:589

**Key findings**: the largest substantive fixes were (1) the §2.12 validation-order resequence — impl uniformly resolves path/body resources before party/SoD checks, opposite to the finalized order; (2) the unenforced railcar-mark uniqueness claim; (3) the open-work-orders departure guard applying from `READY_FOR_DEPARTURE` as well. Everything else in the impl (state machines, dual pricing, decision table, ceilings, dwell variants, ledger posting, sweep semantics, envelope) was already uniquely pinned by PRD_FINALIZED.md and left untouched.
