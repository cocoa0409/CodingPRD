# Worklog — task_1283_hose_fittings_hydraulic_shop_counter

## Step 1: Create Task Directory — 2026-08-12T19:23:00.000Z

Task directory `tasks/task_1283_hose_fittings_hydraulic_shop_counter/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher; Step 1 treated as DONE per invocation instructions.

## Step 2: Generate Scaffold — 2026-08-12T20:07:00.000Z

Scaffold generated and lint-clean. Summary:

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1283_hose_fittings_hydraulic_shop_counter/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (response envelope, entities, state machines, concurrency, calculations, validations, endpoints, errors, RBAC). No `scaffold_difficulty_design`/`scaffold_corner_design` keys.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8).
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9).

**Counts:**
- Entities: 8 (Customer, EquipmentAsset, Reel, Coupling, AssemblyOrder, AssemblyLine, Inspection, ServiceDispatch)
- State machines: 5 (AssemblyOrder — cyclic rework loop; Inspection — PASSED/FAILED branch + SUPERSEDED; ServiceDispatch — linear with abort; Reel — threshold auto-transitions + RETIRED; EquipmentAsset — ACTIVE→DECOMMISSIONED)
- Calculations: 5 (assembly_price with provisional/final variants, assembly_invoice_total pinned rounding order, cut_waste_allocation threshold, next_due_date, compliance_score with strict/projected variants)
- Validations: 20 ordered rows; Errors: 26; Endpoints: 36; Roles: 5 (Customer is `entity_backed:Customer`, rest opaque)
- Difficulty instances: 18 (2 per rule × 9 rules)
- Corner instances: 36 active + 3 `excluded_because` stubs

**Design highlights:** compliance_audit archetype + pricing_engine secondary; flat topology; OCC on `EquipmentAsset.version` for inspection create-with-supersede; depth-3 cascade (order complete → asset install → posture → customer score) and depth-2 cascade (cancel → reel restore → status flip); half-open van windows vs closed inspection windows for the two overlap semantics; reel-millimeter and coupling-unit conservation invariants.

**Verification:** `scaffold_lint.py` reports `VERDICT: clean lint` (286 calls scanned, all conform to §1.5; all FKs reverse-reachable). All formula-derived assert literals (10900/12400, 13770, 3501, date arithmetic, waste 120, mid-tier 4000) were executed and verified numerically.

## Step 3: Copy Shared Files — 2026-08-12T20:08:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1283_hose_fittings_hydraulic_shop_counter/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T20:25:00.000Z

All verifications pass. The PRD is complete.

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1283_hose_fittings_hydraulic_shop_counter/workspace/PRD.md` — 281 lines.

**Sections covered**
- **§1 Introduction** — 2 paragraphs (counter workflow + hose-management program angle)
- **§2 Global Specifications** — 11 domain-derived subsections: RBAC (2.1), verbatim response-structure block (2.2), pagination (2.3), common resource properties incl. the AssemblyLine exception — only `id`/`created_at`, no `updated_at`/`version` (2.4), the logical clock pinned at 2026-08-01T00:00:00Z (2.5), pinned rounding order (2.6), reel length ledger with 1m/20m waste thresholds (2.7), pressure/crimp/waiver safety rules (2.8), half-open van vs. closed-interval inspection window arithmetic (2.9), OCC (2.10), and the full validation ladder with left-to-right nested-resource retrieval (2.11)
- **§3 Business Logic** — 7 subsections grouped by shop workflow: customer book & fleet registration, stocking reels/couplings, draft-quote-confirm, build bench (crimp/test/rework/tag), settlement & the 7-state cancellation matrix, emergency dispatch, and inspections/compliance scoring
- **§4 Endpoint table** — 36 rows, 4 columns, verified row-for-row against the scaffold (method, path, roles)
- **§5 Error catalogue** — 26 rows, 2 columns, verified against the scaffold

**Hard contract reports**
- Contract 1 (field coverage): entities[].fields 68/68 present; endpoints[].request_body+query 49/49; common/envelope 14/14 — **PASS**
- Contract 2 (rule coverage): all 20 validations expressed with priority ordering (global ladder in 2.11 plus per-endpoint sequences for confirm/dispatch/inspection-create); the single OCC rule fully expressed (`expected_equipment_asset_version` + `ERR_STALE_VERSION`/412, no race framing); all 4 state machines' transitions with preconditions and side-effects; all 5 calculations (assembly_price dual-variant with 150/200/260 cents-per-minute tiers, pinned invoice rounding, cut-waste allocation, next_due_date, strict/projected compliance with the 70-point probation bar) rendered as reconstructible prose; all `applies_to` scopes enumerated; sibling branches (7 cancel states, 2 test results, 3 retire states, pass/fail inspections) at equal density — **PASS**
- Contract 3 (§3 path purity): 303 backticked tokens scanned, 0 paths, 0 bare HTTP methods, 0 combos — **PASS**

**Notable generation decisions**: §2.2 emitted byte-for-byte verbatim (fenced JSON blocks initially broke my naive backtick-pairing checker — tokens after fences appeared missing until fences were stripped from the check input, a checker artifact, not a document defect); labor-tier and waste constants embedded with unit conversions ("one meter", "twenty meters", "half an inch"); the scaffold's unusual lowest-priority placement of `ERR_INVALID_REQUEST` (priority 20) transcribed faithfully as the last rung of the validation ladder; cancel-restoration asymmetry (reel restored only from CONFIRMED, tag serial freed only from TAGGED) rendered state-by-state; two fuzzy-word hits ("more or less", "around it") found by scan were rewritten before shipping. The withheld `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened.

## Step 5: Generate Unit Tests — 2026-08-12T20:50:00.000Z

Generation complete. Summary:

**Queue A (Difficulty, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`): 36 tests** — all 18 instances × 2 tests each, every docstring tagged `Design: Difficulty/<rule_id>/<instance.name>`. Coverage spans both dual-variant calcs (quoted-vs-final pricing; strict-vs-projected compliance), both combinatorial formulas (emergency tier+discount at 13770; pinned rounding at 3501), both cyclic state machines (rework loop; inspection pass/fail branching), both transitive cascades (completion depth-3; cancel-restores depth-2), both priority pairs (terminal-beats-credit-hold; pressure-beats-retired-reel), both boundary checks (cut == remaining; on-time == due date), both cross-entity gates (depleted reel; decommissioned asset), both overlap semantics (half-open van vs closed inspection interval), and both conservation invariants (reel mm; coupling units).

**Queue B (Corner, `SCAFFOLD_CORNER_DESIGN.yaml`): 36 tests** — all 36 non-stub instances × 1 test each, tagged `Design: Corner/<section>/<instance.name>`.

**Skips (all `excluded_because:` stubs; pointers verified, no placeholders emitted)**
- `Corner/state_machines/cancel_completed_order_returns_terminal` → owned by `Difficulty/.../terminal_state_beats_credit_hold` (my second test on that instance asserts cancel-on-COMPLETED → `ERR_ORDER_TERMINAL`)
- `Corner/state_machines/reel_auto_status_depleted_on_confirm` → owned by `cut_length_exactly_equals_remaining`
- `Corner/calculations/next_due_recompute_on_install` → owned by `order_completion_cascade_depth3`

No instance failed the PRD-first filter; nothing else was skipped.

**Files written**
`test_helpers/` (9 files): `types.py` (enums + TypedDicts; `AssemblyLine` correctly omits `updated_at`/`version`), `api_client.py` (36 endpoint methods, all under the `/api` prefix this task declares), `api_errors.py` (26 errors, registered with the framework status map), `assertions.py` (per-entity assertions + format-agnostic `assert_instant_equal` for clock-stamped timestamps), `factories.py`, `constants.py` (MIN_REMNANT_MM 1000, LOW_THRESHOLD_MM 20000, labor tiers 150/200/260, ×1.5 emergency, 2.0 test-pressure, probation 70), `test_users.py` (5 roles + `make_customer_headers` for the entity-backed Customer role), `fixtures.py` (lifecycle composites: confirmed→built→test-passed→tagged→completed orders, inspection scheduling/start/complete, dispatch advance), `__init__.py` barrel.

`test_suite/` (9 files): `conftest.py` + 8 test files (72 tests total, collected cleanly by pytest).

**Verification performed**
- pytest collects all 72 tests with zero import errors.
- Automated audit: every test has exactly one Design tag; every queue-A instance has ≥2 tests; every non-stub queue-B instance has ≥1; no bogus tags; all 3 stub pointers resolve.
- Citation audit: every `PRD §x.y` quoted sentence in every docstring survives whitespace-normalized literal match against `PRD.md` (0 failures).
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold/table references in generated code comments.

Two derivability judgment calls worth noting: (1) the corner instance asserting `version == 1` on a fresh reel was emitted without the absolute version assertion — the PRD pins the +1-per-modification increment but not the initial value, so version checks are done relatively (captured before/after); (2) timestamp equality is asserted by parsed instant, not string equality, since the PRD pins instants (logical clock) but not serializer formatting.

## Step 6: Generate Implementation — 2026-08-12T20:50:30.000Z

Done. Summary of the completed implementation for task_1283:

**Files written** (all under `workspace/implementation/`)
- `start.sh` — executable launcher; guarded dependency install (`python3 -c "import flask"` check, no re-install on per-test reboots), `exec python3 app.py` in foreground
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask entry point, ApiError/404/405/500 handlers, binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory store (dicts keyed by id, **empty at every boot, zero seeding**), logical clock defaulting to `2026-08-01T00:00:00Z`, `new_entity`/`touch` (version starts at 1, +1 per mutation, cascades touch related resources per PRD §2.4), ISO-8601 3-fractional-digit formatter
- `errors.py` — full 26-entry error catalog with exact scaffold IDs/statuses
- `response.py` — exact envelope: `{meta:{api_request_id, api_request_timestamp}, response_type, data}`; error variant with `data:{error_id, message}`; list meta carries `limit/offset/total_count/has_more`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (5 roles), Customer-role ownership scoping, typed field getters, pagination (limit 1–100 default 10, offset 0)
- `services.py` — Decimal round-half-up pricing with the pinned per-component rounding order (hose → lines → labor → waste → subtotal → discount last), labor tiers (150/200/260 cpm by diameter 0.5/1.0 in), 1.5x emergency multiplier, cut-waste allocation (MIN_REMNANT_MM 1000, LOW_THRESHOLD_MM 20000), reel status ladder (bidirectional, RETIRED terminal), derived coupling `reserved_qty`/`available_qty`, next-due-date and compliance-posture chains (frozen on DECOMMISSIONED), strict/projected compliance scores (2dp half-up, 100.00 when no ACTIVE assets, PROBATION threshold 70, DUE_SOON 30d), shared TAGGED→COMPLETED settlement cascade
- `routes/` — `clock`, `customers`, `assets` (incl. OCC-guarded inspection create with supersede), `inspections`, `reels`, `couplings`, `orders`, `dispatches`

**Endpoints implemented (all 30 from the scaffold)** — Customers, equipment-assets, nested inspections, inspections start/complete, reels, couplings, assembly-orders (full lifecycle), service-dispatches, and `POST /api/_clock/set_current_utc`.

Validation follows the PRD §2.11 ladder exactly: auth → forbidden → existence (left-to-right, per-resource 404 IDs; missing required FK → 400, unknown FK → 404) → order terminal lockdown → state → OCC → safety (pressure/waiver/crimp/test-pressure) → temporal (window shape, half-open van overlap, closed-interval inspection overlap) → tag uniqueness → referential → fiscal → malformed-request last. Confirm runs the PRD §3.3 fixed sequence: pressure → waiver → reel usable → credit hold → length → coupling stock.

**Boot-check results**
- `bash start.sh` boots cleanly on `$PORT`, serves within ~2s, install guard makes reboots a no-op
- Fresh-boot store verified empty (list `total_count: 0`); a second boot after writes confirmed **no state carry-over**
- 110-check end-to-end smoke suite passed 110/110, covering: full order lifecycle (draft→confirm→build→fail→rework→rebuild→pass→tag→complete), quoted 30060 vs final 32760 cent-exact pricing, scrap/waste accounting (500 mm remnant → 2000-cent surcharge, reel DEPLETED→restored on CONFIRMED cancel, untouched on BUILT cancel), tag uniqueness, dispatch van overlap (touching endpoints allowed, abort frees window), dispatch-complete order installation, inspection OCC 412, supersede, closed-interval conflict, overdue/NON_COMPLIANT posture flips, strict-vs-projected score divergence, PROBATION discount cutoff, decommission freeze, RBAC/ownership, and pagination

One environment note: this host has concurrent agents whose `pkill -f "python3 app.py"` patterns killed my manually-started test servers between checks — harmless for the harness (it owns the process lifecycle via `start.sh`), but worth knowing if manual verification looks flaky.

## Step 7: Run Tests and Iterate — 2026-08-12T21:20:00.000Z

**Iterations run:** 3 eight-round sweeps (72 tests/round).

**Tests deleted:** none — every failing assertion traced to verbatim PRD prose with unique derivability; no PRD-silent or scaffold-only tests were found.

**Fixes applied to `test_suite/`:**
- `test_suite/test_04_completion_cascade_and_couplings.py` — `TestCouplingUnitConservation._setup(self)` → `_setup(self, api)` and both call sites updated: the helper called `api.create_coupling_receipt(...)` but `api` is a pytest fixture that only injects into test methods, so it raised `NameError` in both `test_reservation_holds_then_completion_ships_units` and `test_conservation_holds_after_cancel_releases_reservation` (all 8 rounds).
- `test_suite/test_05_inspections_compliance_and_occ.py` — `TestAssetActiveGating._setup_decommissioned_with_scheduled(self)` → `(self, api)` and both call sites updated: same `NameError` pattern via `api.decommission_equipment_asset(...)` in `test_start_blocked_by_decommissioned_asset` and `test_schedule_blocked_by_decommissioned_asset` (all 8 rounds).

**Fixes applied to `test_helpers/`:** none — helpers were PRD-consistent throughout.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes/reels.py` (`create_reel`) — the fresh reel's status was hardcoded `"AVAILABLE"`; it now applies the §2.7 status ladder (`reel_status_for(initial)`). PRD §2.7 defines the ladder unconditionally ("A reel is `AVAILABLE` while its remaining length is at least twenty meters. It becomes `LOW` once the remainder drops below twenty meters but still reaches at least one meter.") and §3.2 explicitly delegates the fresh reel's status to "the status ladder from §2.7". Verified both branches live: 6000mm → `LOW`, 50000mm → `AVAILABLE`. This fixed `test_confirm_on_low_reel_is_allowed` (all 8 rounds).

**Infrastructure flakes (no artifact change):** sweeps 1–2 also showed "API server could not be restarted" setup errors (full 15s poll window expired) at scattered tests. Root cause is host-level contention — the box runs ~15 other concurrent `prd-bench-entrance` pipelines, and our 8 lockstepped rounds all restart a server at the same wall-clock instants, so one host stall errors the same test index in every round. A controlled repro of the exact restart sequence (8-way concurrent, 240 restarts, instrumented) produced 0 failures, confirming no task-side defect; the runner's port registry, LISTEN-only kill, and DNS-boot patch are all functioning. Sweep 3, run as contention ebbed, passed 72/72 in all 8 rounds.

## Step 8: Finalize PRD — 2026-08-12T21:35:00.000Z

Done. `PRD_FINALIZED.md` is written with exactly one revision.

**Line counts and delta**
- `PRD.md`: 281 lines; `PRD_FINALIZED.md`: 281 lines — 0% line-count delta (one in-place paragraph revision; +124 characters on the touched line).

**Changes (one total)**
- **§3.2 (Stocking the Shop: Reels and Couplings)** — **revise** — the clause "the status ladder from §2.7 puts the fresh reel at `AVAILABLE`" became "the fresh reel's `status` is assigned by applying the status ladder from §2.7 to the full received length — a reel received with at least twenty meters starts `AVAILABLE`, one below twenty meters but still reaching at least one meter starts `LOW`, and one below one meter starts `DEPLETED`" — `implementation/routes/reels.py:30` (`"status": reel_status_for(initial)`), ladder at `implementation/services.py:39-44`.

Rationale: the old sentence, read literally, asserts every fresh reel is `AVAILABLE` — that is exactly what the buggy pre-fix implementation did. Step 7 fixed `create_reel` to apply the §2.7 ladder to the initial length (verified live: 6000mm → `LOW`, 50000mm → `AVAILABLE`), so the PRD text was a genuine impl mismatch / non-unique derivability and had to be reworded. The other two step_7_diff items (`test_04` `_setup(self)` and `test_05` `_setup_decommissioned_with_scheduled(self)`) are pure pytest fixture-injection `NameError` bugs; the behaviors they exercise (§3.2/§3.5 coupling conservation, §3.1/§3.7 asset-active gating) are already pinned verbatim in the PRD and correctly implemented, so they required no PRD edit.

**Per-edit pre-edit search log (NO-NEW-MISMATCH RULE)**
- **Edit 1 (§3.2 fresh-reel status clause)**
  - (a) Subject: the initial `status` value assigned to a reel at receipt (`POST /api/reels`).
  - (b) Impl paths enumerated and read/grepped: (1) `implementation/routes/reels.py:14-33` `create_reel` — applies `reel_status_for(initial)` with `initial_length_mm >= 1`, so receipt-time `DEPLETED` (1–999mm) is reachable; (2) `implementation/services.py:39-44` `reel_status_for` ladder definition; (3) `implementation/services.py:47-51` `refresh_reel_status` (skips `RETIRED`) and both call sites `implementation/routes/orders.py:231` (confirm commit) and `:348` (cancel-from-CONFIRMED restore) — later-lifecycle recomputation, governed by §2.7/§3.3/§3.5, untouched by the reworded clause; (4) `implementation/routes/reels.py:43-51` `retire_reel` — orthogonal; (5) PRD cross-references grepped for consistency: §2.7 ladder (unconditional, consistent), §3.3 confirm gate "AVAILABLE or LOW" (consistent — a fresh sub-1m reel simply cannot be confirmed against, matching §2.7's "no further order can be confirmed against it"), §3.2 retire sentence "available from `AVAILABLE`, `LOW`, or `DEPLETED` alike" (consistent with a fresh reel starting in any of the three).
  - (c) Wording adjustment: yes — the clause was scoped to receipt-time only and spells out all three possible outcomes including `DEPLETED`, because `create_reel`'s `min_val=1` makes a sub-1000mm initial length legal and ladder-`DEPLETED` at receipt.

## Step 9: Complete PRD — 2026-08-12T21:55:00.000Z

Done. `PRD_COMPLETED.md` produced.

**Source/delta**: copied from `PRD_FINALIZED.md` (281 lines / 43,581 chars) → `PRD_COMPLETED.md` (281 lines / 47,536 chars), char-delta +3,955. All edits are in-paragraph inserts/revisions; no sections added, no restructuring.

**Counts**: 18 ambiguity-pins, 2 mismatch-revisions (20 paragraph-level edits total).

**Changes** (section — insert|revise — ambiguity|mismatch — what changed — impl ref):
- §2.1 — insert — ambiguity — Customer-role list endpoints enforce ownership by filtration (own records only; foreign `customer_id` filter yields an empty page, not 403) — routes/assets.py:54-58, routes/orders.py:142-145
- §2.2 — revise — ambiguity — `api_request_timestamp` is read from the logical clock, not wall-clock time — response.py:20
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped into range; non-integer values are `ERR_INVALID_REQUEST` (400); unrecognized filter values match nothing — middleware.py:166-177
- §2.3 — insert — ambiguity — `created_at`-ascending ties break by creation (insertion) order — response.py:47, db.py:13-14
- §2.4 — revise — ambiguity — `version` starts at 1 on creation, when `created_at` equals `updated_at` — db.py:46-49
- §2.5 — revise — ambiguity — clock-set responds 200 OK; all datetime inputs share one parser (trailing `Z` either case; offset-less timestamps read as UTC) — clock.py:18, middleware.py:143-155
- §2.10 — insert — ambiguity — missing or non-integer `expected_equipment_asset_version` fails at the OCC rung with `ERR_INVALID_REQUEST` (400) — routes/assets.py:99-103
- §2.11 — revise — mismatch — PRD pinned authorization strictly before existence; impl applies the ownership check to the path id itself only on the customer-record endpoint (403 even for unknown ids), and to the resolved resource everywhere else (unknown path id 404s first) — routes/customers.py:38-39 vs routes/assets.py:72-73, routes/orders.py:160-161
- §2.11 — revise — mismatch — "malformed strictly dead last" replaced with impl reality: null counts as absent; non-object body is an immediate 400, absent body is `{}`; fixed field types (pressures/lengths/quantities/labor-minutes/cents are integers with booleans never accepted; diameters/tolerances/sizes/discount-rate are numbers); only range minima are those §3 states; body FKs resolve at the existence rung in §3 naming order with an absent required key failing as `ERR_INVALID_REQUEST` there; rule-consumed fields are shape-validated at their rule's rung — middleware.py:62-131, routes/orders.py:49-87,209-216,242-258,266-282,303-311
- §3.1 — revise — ambiguity — `program_discount_pct` accepted without range restriction; every update call counts as a modification; interval "change" means the submitted value differs from the stored one — routes/customers.py:26,54-67
- §3.1 — revise — ambiguity — re-decommissioning fails with `ERR_INVALID_STATE`; the frozen posture is exposed on the asset as `frozen_posture` (null while active) — routes/assets.py:81-90, services.py:106-107
- §3.2 — revise — ambiguity — re-retiring a `RETIRED` reel fails with `ERR_INVALID_STATE` — routes/reels.py:47-48
- §3.2 — revise — ambiguity — a stock receipt's `quantity` must be at least 1 — routes/couplings.py:43
- §3.3 — revise — ambiguity — confirm-time coupling check is per-line against full `available_qty`, no cross-line accumulation for shared couplings — routes/orders.py:203-208
- §3.3 — insert — ambiguity — waiver pair is all-or-nothing: only one of the two fields present stores nothing — routes/orders.py:233-236
- §3.5 — revise — ambiguity — `final_total_cents` samples the customer's `program_status` and `program_discount_pct` as they stand at completion — services.py:226,232-237
- §3.5 — revise — ambiguity — cancelling `CONFIRMED` against a since-retired reel still credits the lengths but the reel stays `RETIRED` — routes/orders.py:342-349, services.py:47-51
- §3.6 — insert — ambiguity — a completed dispatch lands in `COMPLETED` and records `installed_assembly_order_id` when supplied — routes/dispatches.py:128-130
- §3.7 — insert — ambiguity — `performed_at` ties among completed inspections break in favor of the most recently created — services.py:92-100
- §3.7 — revise — ambiguity — both compliance scores (not just strict) are 2-decimal half-up and read 100.00 with no active assets — services.py:136-148,166-167

All endpoint paths, role sets, state machines, pricing/rounding formulas, reel-length arithmetic, window-conflict semantics, error-id/HTTP-status catalog, and OCC mechanics in the PRD were verified to already match the implementation uniquely and were left untouched.
