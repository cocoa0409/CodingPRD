# Worklog — task_2512_life_science_building_conversion_tenant_fit_out

## Step 1: Create task directory — 2026-09-03T03:33:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2512_life_science_building_conversion_tenant_fit_out/` and its `workspace/` subdirectory. Index 2512 was pre-assigned by the orchestrating command (no scan of `./tasks/` performed, per instruction, to avoid collision with the up-to-32 concurrent pipelines on this host).

## Step 2: Generate Scaffold — 2026-09-03T05:38:00.000Z

All three scaffold artifacts for task 2512 are complete and lint-clean.

**Files**:
- `SCAFFOLD.yaml`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `SCAFFOLD_CORNER_DESIGN.yaml`

Task 2512 — Life Science Building Conversion & Tenant Fit-Out (life science landlord). Difficulty `expert_plus`; archetypes `multi_party_negotiation` / `quota_allocation`; topology `flat`; state-machine shape `cyclic`; role model `segregation_of_duties`; consistency `immediate`; complexity layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `rate_threshold_triggers`.

SCAFFOLD.yaml (§1.0–§1.7): 14 entities (Building, Floor, SuitabilityAssessment, ConversionScopeItem, Tenant, Lease, TIProposal, FitOutProject, PhasePackage, CapacityReservation, HazmatUsePermit, SharedAmenity, AmenityAllocation, CommissioningRecord), 12 state machines, 2 OCC concurrency rules (`reservation-create-stale-building`, `ti-proposal-create-stale-lease`), 8 calculations (control-area/MAQ allowance, suitability score, floor hazmat utilization, TI final allowance, phase TI commitment, TI draw allocation, building capacity pools, restoration liability), 74 ordered validations, 69 endpoints (36 POST / 33 GET, incl. the `/_clock/set_current_utc` driver and the `GET /floors/{floorId}/hazmat-utilization` computed read), 68 errors, 5 roles (LandlordAssetManager, BaseBuildingEngineer, Tenant, AHJPermitOfficer, CommissioningAgent).

SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8): 9 hard rules × 2 = 18 instances (`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`).

SCAFFOLD_CORNER_DESIGN.yaml (§1.9): 9 sections, 81 instances — 57 live `test_recipe` instances + 24 `excluded_because` stubs. Per section: entities 11, state_machines 13, calculations 15, validations 12, endpoints 7, errors 9, rbac 4, complexity_layers 9, consistency_model 1. `bulk_action` omitted (no bulk endpoints in §1.5).

Verification: `scaffold_lint.py` → **clean lint** over 1439 §1.8+§1.9 calls (all calls conform to §1.5; all §1.1 FKs reverse-reachable). Additional self-checks all pass: all 68 catalog errors triggerable, no undeclared error id cited, 99/99 instance names unique across both design files, every stub cites an existing §1.8 instance and carries no `test_recipe`, every dotted/bracket `grounds` reference resolves to §1.1–§1.7, every asserted error id is declared on an endpoint actually exercised, every asserted entity field/enum value exists, no forbidden concurrency vocabulary.

Defects found and fixed during the final replay pass: `round_no` → `round_number`; wrong post-round-1 lease state (COUNTER_PENDING → NEGOTIATING) and non-existent `SUPERSEDED` proposal status → `COUNTERED`; `Building.status` → `Building.suitability_state`; `HazmatUsePermit.decided_at` → `decision_reason`; hazmat utilization percentages re-rounded to the declared 2 dp (were 4 dp); `ERR_CONTROL_AREA_MAQ_EXCEEDED` status 422 → 409; hold cascade assert corrected to `C_NOT_STARTED` (the `C_IN_PROGRESS → C_SUSPENDED` clause needs a phase that reached IN_PROGRESS); per-control-area report basis corrected to include REQUESTED permits (190.00/40.00) as the calculation's `PER_CONTROL_AREA_STATUSES` requires; six invented validation/calculation rule_ids replaced with the real ones.

## Step 3: Copy shared files — 2026-09-03T05:38:30.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-03T05:55:00.000Z

PRD generated at `workspace/PRD.md`.

**Size:** 447 lines, 13,431 words, 97,582 bytes. Ends at a completed §5 (last row `| `ERR_WITNESS_CONFLICT` | 403 |`), no mid-sentence truncation. Written as six staged part files then concatenated once in order; part files removed. Byte totals of the parts sum to the final file, so no append clobbered another.

**Sections:** §1 Introduction; §2 Global Specifications with 2.1 RBAC, 2.2 API Response Structure (verified byte-identical to `skills/prd-bench-doc-generator/section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Resource Identity/Audit Fields/Logical Clock, 2.5 Flat Collections & Left-to-Right Path Resolution, 2.6 Version Preconditions, 2.7 Rounding Discipline, 2.8 Rejection Precedence, 2.9 Separation of Duties, 2.10 Cascade Propagation & the Two Conservation Identities; §3 Business Logic with nine subsections (3.1 base building & floor plates, 3.2 suitability & conversion approval, 3.3 tenants & TI negotiation, 3.4 execution/escrow/TI ledger, 3.5 fit-out projects/permitting/capacity reservations, 3.6 phased delivery/windows/vibration holds/cascades, 3.7 shared amenities & allocation programming, 3.8 hazmat & control-area limits, 3.9 commissioning/acceptance/lease wind-down); §4 Endpoint Definitions (4 columns: Method, Path, Description, Authorized Role(s)); §5 Error Code Catalogue (2 columns: Error ID, HTTP Status Code).

**Coverage audit (machine-verified against SCAFFOLD.yaml):**
- Entities: 14/14 — every one of the 138 distinct entity field names appears verbatim in backticks.
- State machines: 12/12 (FitOutProject appears twice, `permit_status` and `construction_status`, both documented as independent dimensions). All states present; 62/62 transitions stated — 52 matched the arrow form automatically, the remaining 10 verified by hand as spelled-out prose.
- Calculations: 8/8 — MAQ allowance (§3.8), suitability score & verdict (§3.2), two-basis floor utilisation (§3.8), final TI allowance/authorised dollars (§3.3), phase eligibility & chronological commitment waterfall (§3.6), draw cap & pro-rata allocation with signed residual (§3.4), pool conservation (§2.10/§3.2/§3.5), restoration liability & settlement waterfall (§3.9).
- Validations: 74/74 — grouped into 31 endpoint orderings, each with its priority order stated explicitly in prose.
- Endpoints: 69/69 rows in §4, paths and role lists generated directly from the scaffold.
- Errors: 68/68 rows in §5, and all 68 identifiers also appear in §1–§3 prose.
- Roles: 5/5, spelled exactly, with `Tenant` as the sole entity-backed identity.

**Hard contracts:** Contract 1 (Field-Name Coverage) PASS — 163 required identifiers, 0 missing. Contract 2 (Rule Coverage) PASS — both OCC rules with protected invariants, all cross-entity cascades, `applies_to` scopes for the two distinct MAQ bases, sibling-branch symmetry. Contract 3 (§3 Path Purity) PASS — 0 path/method tokens in §3, no fuzzy quantifiers, no pseudocode.

One judgement call flagged by the generator: the scaffold leaves `control_area_index` optional on the floor hazmat-utilisation report with no stated default, so the PRD specifies it defaults to control area 1, and fixes the report's `use_condition` factor at `CLOSED_SYSTEM_USE`, making the report a deterministic function of floor and hazard class.

**Orchestrator verification:** independently confirmed tail ends at completed §5 error table; `grep` counts 69 endpoint rows and 68 error rows; all 5 top-level sections present.

## Step 6: Generate Implementation — 2026-09-03T06:32:00.000Z

Implementation complete and validated.

## Files written

All under `workspace/implementation/` (22 files, 3,316 lines):

`start.sh` (guarded `pip install` then `exec python3 app.py`, honours `$PORT`, default 10000), `requirements.txt` (`flask>=2.0`), `app.py` (factory + error handlers), `constants.py`, `errors.py` (~70-entry `ERROR_CATALOG`), `util.py` (Decimal/ROUND_HALF_UP + ISO helpers), `clock.py` (logical clock), `db.py` (14 in-memory dicts, `new_id/create/touch/ordered`), `response.py` (envelope), `validation.py`, `auth.py`, `queries.py`, `calc.py`, `serializers.py`, `cascades.py`, `helpers.py`, and `routes/{__init__,core,assessments,leasing,delivery,facilities}.py`.

Module layout: shared primitives at the top level, five route blueprints registered flat at `api_prefix: "/"`. Storage is process-local dicts only — no SQLite, no JSON dump, no `/tmp` cache, no file I/O anywhere in the tree (grep for `open(`/`json.dump`/`sqlite`/`pickle` returns nothing), and nothing is seeded: a cold boot answers `GET /floors` with `total_count: 0`.

## Endpoint coverage

69 routes registered; a set-diff of `(method, normalised path)` against every `- method:` block in `SCAFFOLD.yaml` is exact in both directions (`scaffold only: []`, `mine only: []`).

## Boot behaviour

Verified for `--isolation per-test-server`: two consecutive fresh `start.sh` launches on clean ports were both serving in ~0.62 s with an empty store.

## PRD ambiguities resolved

1. Auth headers: PRD 2.1 `X-User-ID` + `X-User-Role` (role values are the long PRD names, e.g. `LandlordAssetManager`) chosen over the scaffold's `X-Role`/`X-Tenant-Id`.
2. `created_at` uses the logical clock; ordering ties broken by insertion sequence.
3. Global precedence: body/query parsed and validated *before* `auth.require(...)` in every handler, so ERR_VALIDATION (422) always precedes ERR_UNAUTHORIZED (403), then path 404, then body-FK 404, then domain rules.
4. Tenant ownership checked after FK resolution, before domain rules — except `POST /amenity-allocations/{id}/cancel`, where the documented order is state -> tenant scope -> future-window (reported as `ERR_INVALID_ALLOCATION_STATE`).
5. Round 1 opened by a Tenant (undocumented): lease becomes `NEGOTIATING` if the author is the landlord, `COUNTER_PENDING` if the tenant.
6. `POST /ti-proposals/{id}/accept` returns the Lease.
7. Assessment-submit's "building must be ASSESSING" precondition is unreachable and has no error id, so it is not enforced.
8. Building `version` bumps once per request, and at acceptance/settlement only if at least one reservation actually transitioned.
9. `delivery_risk`, `passed_script_count`, pool figures and `scope_disciplines_*` are derived on read (structurally guaranteeing both conservation identities); project version bumps only when a stored field changes.
10. Hold cascade applies amenity preemption unconditionally; the BLOCKED-restore cascade fires only on `VIBRATION_HOLD -> SCHEDULED`.
11. Commissioning FAIL clawback reverses every phase in the recorded last-draw allocation set, bumping each phase version.
12. `expiration-notice` treats `expiration_date < now` as ERR_VALIDATION in the validation step (before the role gate and lease lookup), per global precedence step 1.
13. `hold_reason` / `return_note` / `decision_reason` are parsed as optional raw strings so blank/null surfaces as the documented domain error at its own priority; `control_area_index` is validated only as an integer so out-of-range yields `ERR_CONTROL_AREA_OUT_OF_RANGE`.
14. List endpoints are not tenant-filtered (ownership is enforced on single-resource reads and mutations); `GET /tenants/{id}` is not tenant-guarded.
15. `schedule` on a lease with a null `executed_at` yields `ERR_WINDOW_OUTSIDE_DELIVERY_TERM`; amenity concurrency is re-evaluated at confirm excluding the allocation itself.
16. `permit-decision` accepts only `decision: "ISSUE"`; `construction-milestone` only `milestone: "SUBSTANTIAL_COMPLETION"`.
17. Decimals are quantized (2 dp default, 1 dp score, 4 dp headroom, integer credits) and emitted as JSON numbers.

## Numeric validation

An out-of-tree smoke script (`/tmp/smoke2512.py`, not in the task directory) exercises every worked example in the scaffold and reports `FAILURES: 0`: control areas 3 / 0.75 and 2; SCREENING 78.0 SUITABLE vs INVESTIGATION 33.0 UNSUITABLE with headroom 1.1429; pools 80,000 CFM / 1,200 kW; L1 provisional 5,021,500.00 -> credit 3.00 -> final 204.50 -> authorized 4,948,900.00, escrow 250,000.00; TI commitments 114,750.00 / 20,060.00 / 36,000.00 (lease committed 170,810.00, uncommitted 329,190.00); draw 150,000.00 split 100,769.87 / 17,616.06 / 31,614.07 with the +0.01 residual to the earliest phase; hazmat allowance 180.00 with 94.44 % / 27.78 % utilisation plus the cross-project floor-wide `ERR_CONTROL_AREA_MAQ_EXCEEDED`; FAIL clawback to 0.00 and redraw; the 4-hop acceptance cascade (project C_ACCEPTED, reservation COMMITTED, permit ACTIVE, lease ACTIVE, 18,000 CFM shifted reserved->committed with availability unchanged at 62,000); and the restoration waterfall (liability 601,550.00, escrow refunded 0.00, cash due 222,360.00, forfeited 350,000.00, disbursed+forfeited = authorized 500,000.00, permits SURRENDERED, reservation RELEASED, pool restored to 80,000.00), plus envelope/error-shape and pagination-meta assertions.

Note: the subagent did not read anything under `test_helpers/` or `test_suite/`, nor any other `task_*/` directory. All test servers it launched were shut down and their ports freed.

## Step 5: Generate Unit Tests — 2026-09-03T07:33:00.000Z

Test generation for task_2512 is complete.

## Files written

`test_helpers/` (9 modules): `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`

`test_suite/` (conftest + 18 modules):
- Queue A (depth): `test_01_assessment_scoring_depth.py` (6), `test_02_hazmat_allowance_depth.py` (4), `test_03_ti_ledger_depth.py` (6), `test_04_negotiation_cycle_depth.py` (3), `test_05_project_dimensions_depth.py` (4), `test_06_cascade_depth.py` (4), `test_07_precedence_depth.py` (4), `test_08_scheduling_depth.py` (4), `test_09_capacity_depth.py` (4)
- Queue B (breadth): `test_10_entities_corner.py` (10), `test_11_state_machines_corner.py` (9), `test_12_calculations_corner.py` (8), `test_13_validations_corner.py` (7), `test_14_endpoints_corner.py` (5), `test_15_errors_corner.py` (9), `test_16_rbac_corner.py` (4), `test_17_complexity_layers_corner.py` (3), `test_18_consistency_model_corner.py` (1)

## Counts

- **95 tests total** — 39 from queue A (Difficulty), 56 from queue B (Corner).
- Queue A: **18/18 instances covered**, 39 tests (>=2 per instance, no instance skipped).
- Queue B: **56/57 non-stub instances covered**, 1 test each. The 24 stub instances carrying `excluded_because` emitted nothing, as required.

Per-section queue B coverage (live instances -> tests): entities 11->10, state_machines 9->9, calculations 8->8, validations 7->7, endpoints 5->5, errors 9->9, rbac 4->4, complexity_layers 3->3, consistency_model 1->1.

## Instances skipped

One, on the PRD-first filter: `Corner/entities/floor_sprinklered_defaults_false_and_halves_the_maq_allowance`. The instance's distinguishing claim is that `sprinklered` defaults to false and therefore halves the allowance, but PRD §3.1 defaults `sprinklered` to **true** (the 2.0 sprinklered multiplier applies by default). The claim contradicts the contract, so the instance was dropped rather than weakened. No `skip`/`xfail`/placeholder was emitted anywhere.

## Reconciliations (kept, literal corrected)

- `Corner/rbac/each_role_exercises_its_own_exclusive_and_shared_operations` asserted `suitability_state == CONVERSION_COMPLETE`, but the walk declares only `LAB_EXHAUST` and PRD line 179 requires all four disciplines. Since that is an incidental side-assert, the literal was corrected to `CONVERSION_APPROVED` and the test kept.
- The escrow deposit is asserted with lenient `get_success_data` rather than pinned to 201, because PRD line 299 makes it a state change on the lease (bumps `restoration_escrow_held_usd` and the lease version), not an entity creation.

## Verification (all green)

- `pyflakes` clean over `test_suite/` and `test_helpers/` (fixed one unused local in `fixtures.py:983`); `py_compile` clean.
- AST sweep resolving every `from test_helpers import` name, every `ApiErrorId.*` member and every `api.<method>` against the live module plus `ApiClient`/`GenericApiClient`: **BAD: none**.
- `pytest --collect-only`: **95 tests collected in 0.52s**, no import errors, no server launch.
- Design-tag audit: every test has **exactly one** `Design:` line, it is the last docstring line, and all 95 resolve to real non-stub instance names; no dual tags, no tags pointing at stubs.
- No "scaffold" or section/table references in emitted code; no `skip`/`skipif`/`xfail`/`pytest.mark`; no mocking or monkeypatching.

`workspace/implementation/` was never read or written, and no other `task_*/` directory was touched.

## Step 7: Run Tests and Iterate — 2026-09-03T08:30:00.000Z

**Iterations run:** 6 sweeps (8 parallel rounds each, 48 suite runs total).

### Final sweep — verified per-round results (fresh shell, `workspace/implementation/results.*.json`, all 8 present)

| round | passed / total |
|---|---|
| 1 | 95 / 95 |
| 2 | 95 / 95 |
| 3 | 95 / 95 |
| 4 | 95 / 95 |
| 5 | 95 / 95 |
| 6 | 95 / 95 |
| 7 | 95 / 95 |
| 8 | 95 / 95 |

`failed=0 errors=0 skipped=0` in every file. Union of failing tests across all 8 rounds: empty.

### Tests deleted
**None.** Every failure traced either to a test-artifact bug or to a genuine PRD-required behaviour missing from the implementation, so no test hit the STEP 1a/1b silence or collapse patterns.

### Fixes applied to `test_helpers/`
- `test_helpers/constants.py` — `lease_economics()`: dropped the `subtotal_psf` key from the returned dict. PRD §3 L195 calls the per-square-foot subtotal an intermediate of the seven-step formula ("a per-square-foot subtotal **is formed by** adding...") and never names it as a lease attribute, so tests must not expect it in the lease payload.
- `test_helpers/fixtures.py` — new `get_proposal()` helper, and `accept_terms()` rewritten to read the proposal and the lease back from their own single-resource GET endpoints instead of out of the `POST /ti-proposals/{id}/accept` body. PRD L193 says acceptance touches both resources but never states which one the accept endpoint returns, so the fixture cannot assume it gets the proposal; `bundle["proposal"]` was silently missing `lease_id`/`authored_by_user_id`.

### Fixes applied to `test_suite/`
- `test_suite/test_12_calculations_corner.py` — `test_the_headroom_ratio_is_kept_to_four_places_before_it_is_banded` called `api.submit_assessment()` with no role header and asserted 200; added the missing `ENGINEER_HEADERS`. Fixture bug, not an RBAC defect — PRD reserves assessment submission for `BaseBuildingEngineer`, so the 403 the implementation returned was correct.

### Fixes applied to `implementation/`
- `implementation/serializers.py` — `permit()` now emits `aggregate_allowance_gal`. PRD L267 defines it and §4 L359 requires `GET /hazmat-permits/{permitId}` to return the permit "including its computed allowances".
- `implementation/queries.py` — added `floor_of_permit()`, the traversal the serializer needs to reach `control_areas_allowed`.
- `implementation/app.py` — pinned `WSGIRequestHandler.protocol_version = "HTTP/1.0"`. Transport-only: werkzeug 3.1.8 silently upgrades a `threaded=True` dev server to HTTP/1.1 keep-alive, so the runner's session-scoped pooled `requests.Session` kept handing requests to sockets belonging to a server the per-test `kill -9` had already destroyed (`RemoteDisconnected` / `ConnectionResetError(104)`). Changes no endpoint, field, header, or side effect.

### Key finding on the residual "flakiness"
The transport failures that survived the HTTP/1.0 pin were **not** an artifact defect. In sweep 5 all eight rounds' server logs contain exactly one `^Terminated` — every one of them at the identical wall-clock second, `08:08:06` — i.e. the reaping signature (the runner itself only ever uses `kill -9`/`Killed`; there are zero `Traceback`s in all 40 server logs for this task, and no OOM kills in `dmesg`). Five rounds happened to be between requests at that instant and passed; the three that were mid-request reported `IncompleteRead`/`ConnectionResetError` at three *different* lines of the same test, which is what a single host-wide `SIGTERM` to `python3 app.py` (e.g. another concurrent pipeline running a `pkill -f`-style cleanup) looks like from inside a lockstep 8-round sweep. Re-running the sweep unchanged produced 8/8 clean, confirming external interference rather than a defect. The subagent deliberately did **not** run any `pkill -f`-style cleanup of stray servers, precisely because it inflicts this failure on every other pipeline on the host.

**Orchestrator verification:** independently re-read all 8 `results.*.json` in a fresh shell — every round reports `95/95, failed=0, errors=0, skipped=0`; all 8 files present with matching mtimes (08:25).

## Step 8: Finalize PRD — 2026-09-03T08:45:00.000Z

`PRD_FINALIZED.md` is written. Two edits, both traced to `<step_7_diff>` items.

## Line counts
- `PRD.md`: 447 lines, 97,582 bytes
- `PRD_FINALIZED.md`: 447 lines, 97,990 bytes
- Delta: **0.00% by line count** (both edits are inline sentence insertions into existing paragraphs), **+0.42% by bytes**

## Changes

- **§3.3 (L193, proposal acceptance)** — *insert* — pinned that `POST /ti-proposals/{proposalId}/accept` returns the updated **lease**, not the accepted proposal, and that the proposal's new `status`/`accepted_by_user_id` are observed via a proposal read endpoint — `implementation/routes/leasing.py:242`
- **§3.3 (L195, allowance economics)** — *insert* — pinned that the per-square-foot subtotal (step 2 of seven) is a working intermediate only: stored nowhere, in no response body — `implementation/calc.py:181` / `implementation/serializers.py:114-148`

## Pre-edit search log

**Edit 1 — accept endpoint response body**
- (a) Subject: which resource the accept operation returns, given PRD 2.2's general "returns the created or updated resource" rule and the fact that acceptance mutates two records.
- (b) Paths enumerated: `routes/leasing.py:212-242` (`accept_proposal` -> `response.ok(serializers.lease(lease))`); `response.py:23-29` (`ok` sets `response_type: "object"`, status 200 — so §4 L299 "every other successful operation returns HTTP 200" stays correct); then a full sweep of every `return response.*` in `routes/*.py` (55 sites) to confirm no other endpoint deviates — assessment `decision`/`submit` -> assessment, scope-item `complete` -> scope_item, project `permit-application`/`permit-decision`/`construction-milestone` -> project, phase `schedule`/`hold`/`progress` -> phase, reservation `cancel` -> reservation, allocation `confirm`/`cancel` -> allocation, commissioning `result` -> record (even though it fires the four-hop acceptance cascade), lease `execute`/`escrow-deposits`/`ti-disbursements`/`expiration-notice`/`restoration-settlement` -> lease. The accept endpoint is the *only* place where the returned resource differs from the resource the path names.
- (c) Adjustment: scoped the sentence strictly to acceptance and did **not** state any general "returns the path resource" rule — such a rule would have been true of all 54 other sites but false of the very site being pinned, and would also have over-constrained `commissioning-records/{recordId}/result`, which returns the record while mutating project, reservations, building, permits and lease. Also worded the second clause as "observed by reading the proposal back from a proposal read endpoint" rather than naming `GET /ti-proposals/{proposalId}` alone, since `GET /leases/{leaseId}/ti-proposals` and `GET /ti-proposals` expose the same serializer.

**Edit 2 — the per-square-foot subtotal is not an attribute**
- (a) Subject: whether the step-2 subtotal is persisted on the lease or visible in any response.
- (b) Paths enumerated: `calc.py:175-195` (`ti_economics` — `subtotal_psf` is a local at :181, consumed at :182 and :184; the returned dict holds exactly the six *named* figures `lab_premium_psf_applied`, `provisional_authorized_ti_usd`, `volume_credit_psf`, `final_allowance_psf`, `ti_authorized_usd`, `restoration_escrow_required_usd`); `serializers.py:114-148` (`lease` — full field list, no subtotal key); `routes/leasing.py:76-103` (`create_lease` initial field set, no subtotal); `routes/leasing.py:233-241` (the only writer of the economics block onto the lease — `lease.update(economics)`); `cascades.py` (settlement-time lease writes); plus `grep -rn subtotal implementation/` -> only `calc.py:181/182/184`, and `calc.hazmat_utilization` (`calc.py:63-74`), the one other computed payload assembled outside a serializer, contains no such key.
- (c) Adjustment: verified the universal claim before making it — "stored nowhere and appears in no response body" is safe only because the grep showed zero serializer/payload exposure anywhere, not just on the lease. Added "unlike the other six steps" so the sentence cannot be read as weakening the six sibling figures, which *are* genuine lease attributes emitted by `serializers.lease`.

**No PRD edit** for the remaining `<step_7_diff>` items:
- `serializers.py permit()` emitting `aggregate_allowance_gal` — PRD L267 already defines the figure and §4 L359 already requires the permit read to return "its computed allowances" (plural). Impl fix *toward* the PRD, so pinning it would be redundant.
- `queries.floor_of_permit()` — internal traversal helper, no observable surface.
- `test_suite/test_12` missing `ENGINEER_HEADERS` — pure fixture bug; §4 L316 already reserves assessment submission to `BaseBuildingEngineer`.
- `app.py` HTTP/1.0 pin — transport-only, excluded per instruction.

## Step 9: Complete PRD — 2026-09-03T09:25:00.000Z

**Orchestrator decision (recorded per AUTONOMY):** Step 9 was run as **three sequential, file-partitioned passes** over a single shared `PRD_COMPLETED.md` rather than one monolithic pass. Rationale: a single pass over a 3,323-line implementation and a 447-line/98 KB PRD has repeatedly produced a byte-identical no-op output (the scan silently never runs). Partitioning by implementation module bounds each pass's reading load, and running them sequentially (not concurrently) lets each pass build on the previous one's edits to the same file. The orchestrator performed Method step 0 itself (`cp PRD_FINALIZED.md PRD_COMPLETED.md`, md5-verified) so no pass could clobber a predecessor by re-copying.

Slices: **Pass A** = `app.py`, `auth.py`, `response.py`, `db.py`, `clock.py`, `util.py`, `constants.py`, `errors.py`, `validation.py`, `routes/{__init__,core,assessments}.py`. **Pass B** = `routes/leasing.py`, `calc.py`, `serializers.py`. **Pass C** = `routes/{delivery,facilities}.py`, `cascades.py`, `queries.py`, `helpers.py`.

### Pass A — 12 edits (9 ambiguity-pins, 2 mismatch-revisions; 447 -> 447 lines, in-place)
- 2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly twenty uppercase-letter/digit characters — `response.py:12-13`
- 2.2 — insert — ambiguity — `api_request_timestamp` is read from the wall clock, not the logical clock, and is the only such instant in the system — `response.py:19`, `util.py:74`
- 2.3 — insert — ambiguity — ties on `created_at` (routine, since the clock is logical) break by creation sequence — `db.py:58`
- 2.3 — insert — ambiguity — an identifier-valued filter is never resolved, so a value naming no record yields an empty page rather than a 404 — `helpers.py:24-34`, `routes/core.py:116`
- 2.4 — insert — ambiguity — `created_at`/`updated_at` are read from the logical clock, never the wall clock — `db.py:36,50-52`
- 2.4 — insert — ambiguity — any unrecognised body key is ignored, never rejected — `validation.py`
- 2.8 — insert — ambiguity — explicit JSON `null` counts as absent (required -> missing input; optional -> documented default); a blank/whitespace-only required string is malformed — `validation.py:33-43`
- 3.2 — insert — ambiguity — `measured_floor_to_floor_ft` and `measured_live_load_psf` must be strictly positive when supplied — `routes/assessments.py:37-38`
- 3.2 — **revise** — **mismatch** — removed the "engineer must find the building in `ASSESSING` for the first submission" requirement; submission's only domain rule is the assessment's own status, the building is neither consulted nor version-bumped — `routes/assessments.py:101-112`
- 3.2 — insert — ambiguity — resubmission clears `return_note` but leaves `decided_by_user_id` set — `routes/assessments.py:109-111`
- 3.2 — insert — ambiguity — in `DRAFT` the derived block holds opening values, not nulls: credits 0, ratio 0.0000, score 0.0, `hard_fail_capped` false — `routes/assessments.py:50-63`
- §5 preamble — **revise** — **mismatch** — error identifier is carried in `data.error_id`, not `error.code` — `response.py:42-48`, `errors.py:3`

Verified consistent, no change needed: every role gate in `core.py`/`assessments.py` matches the §4 table; the 68-entry `ERROR_CATALOG` matches §5 one-for-one (scripted, zero diffs); validation-before-role-gate-before-path-404 ordering; 201-on-create/200-otherwise; `has_more`; pagination bounds; malformed-UUID-names-nothing; `complete_scope_item` rule order and `CONVERSION_COMPLETE` bubbling.

Left unpinned by Pass A: `validation.req_num`'s half-even quantization (escalated — see carry-over); `app.py`'s out-of-contract 404/405/500 handlers; `force=True` body parsing ignoring `Content-Type`; empty-string `limit`/`offset`/filter treated as absent.

### Pass B — 18 edits (14 ambiguity-pins, 1 mismatch-revision + 3 further revisions; 447 -> 447 lines, in-place)
- 2.4 — insert — ambiguity — every instant-valued response field is rendered UTC with exactly three fractional digits, so client-supplied instants are echoed normalised; no field is ever omitted — unset values are present and explicitly `null` — `util.py:63`
- 2.7 — insert — ambiguity — the 2-dp discipline governs the carried value, not the wire format: figures serialise as JSON numbers with trailing zeros dropped (`1000.00` -> `1000.0`) — `util.py:41`
- 3.1 — insert — ambiguity — `percent_maq` is a fraction of one (1.00/0.75/0.50/0.25), not a figure out of a hundred — `calc.py:30`, `serializers.py:56`
- 3.2 — insert — ambiguity — `decided_by_user_id` and `return_note` are null until a decision writes them — `serializers.py:81-82`
- 3.3 — insert — ambiguity — a tenant record carries no ownership scope; any authorised role incl. `Tenant` may read any tenant — `routes/leasing.py:47-52`
- 3.3 — insert — ambiguity — the three body identifiers resolve left-to-right `tenant_id` -> `building_id` -> `premises_floor_id`; the premises test runs only after all three resolve — `routes/leasing.py:70-74`
- 3.3 — **revise** — **mismatch** — "an entirely zeroed TI ledger and every negotiated figure null" was false: exactly six figures are null plus the four user/timestamp fields, while every money bucket including `restoration_escrow_required_usd` opens at 0.00 and `negotiation_round_count` at 0 — `routes/leasing.py:76-103`
- 3.3 — insert — ambiguity — `delivery_deadline` is stored as supplied and is not required to be in the future — `routes/leasing.py:66`
- 3.3 — insert — ambiguity — §2.1 ownership governs a single-lease read, but a collection listing is not narrowed to the caller's tenancy — `routes/leasing.py:117-128` vs `:108-114`
- 3.3 — insert — ambiguity — `note` stored as null when omitted; `round_number` counts rounds across every status — `routes/leasing.py:137,155,167`
- 3.3 — insert — ambiguity — a round is created with `accepted_by_user_id` null — `routes/leasing.py:173`
- 3.3 — insert — ambiguity — the lease arc is a function of the author alone regardless of prior status, so a tenant opening the first round drives `LOI -> COUNTER_PENDING` — `routes/leasing.py:175`
- 3.3 — insert — ambiguity — a proposal past `expires_at` still counts as `OPEN` for the turn test, so a party cannot refresh its own stale offer — `routes/leasing.py:151-153` vs `queries.py:49-53`
- 3.4 — insert — ambiguity — no lease-status precondition guards a deposit (accepted in `LOI` through `SURRENDERED`); the response body is the updated lease — `routes/leasing.py:246-255`
- 3.4 — insert — ambiguity — `requested_usd` must be strictly greater than zero — `routes/leasing.py:282`
- 3.8 — insert — ambiguity — the ten fields are the whole utilisation report; it is a computed read carrying none of `id`/`created_at`/`updated_at`/`version` — `calc.py:63-74`
- 3.9 — insert — ambiguity — an `expiration_date` before now yields `ERR_VALIDATION` ahead of the role gate and lease resolution; any status other than `ACTIVE` yields `ERR_INVALID_LEASE_STATE` — `routes/leasing.py:309-315`
- §4 `GET /leases` — revise — description now lists the `building` filter the impl and §3.3 both carry — `routes/leasing.py:120-125`

Left unpinned by Pass B: unreachable empty eligible-phase draw set; dead `control_area_row` fallback; `aggregate_allowance_gal` derived-on-read (unobservable); intra-endpoint body-key validation order (same error id, only `message` differs). Escalated the `validation.py:98` half-even mismatch as a cross-slice carry-over.

### Pass C — 20 edits (9 ambiguity-pins, 8 mismatch-revisions + carry-over; 447 -> 447 lines, in-place)

**Carry-over §2.7 resolved.** Pass C confirmed first-hand that `validation.py:98` is `value.quantize(Decimal(1).scaleb(-places))` with no rounding argument (default `ROUND_HALF_EVEN`), `places` defaults to 2, no callsite of the 28 `req_num`/`opt_num` sites passes `places` or a mode, and the `gt`/`ge` bound check at :94-97 runs on the *unquantised* value. `calc.py` is uniformly half-up via `util.rh`. The blanket sentence "All rounding is half up..." was replaced with prose that keeps half-up for server-computed figures and pins ingest quantization as half-to-even, with worked literals (12.345 -> 12.34, 12.355 -> 12.36, sub-half-cent positive -> 0.00) and the note that integer inputs are never quantised. **No implementation file was touched** — the verified green sweep depends on the implementation byte-for-byte.

- 2.7 — revise — mismatch — as above — `validation.py:90-104`
- 2.8 — insert — ambiguity — the ten POST operations that declare no request fields never parse the body, so a malformed body there is ignored, not 422 — `routes/delivery.py:92,408`, `routes/facilities.py:178,193`
- 3.5 — insert — ambiguity — body ids resolve `lease_id` then `floor_id`; `design_exhaust_cfm`/`design_power_kw` consumed by no rule — `routes/delivery.py:35-45`
- 3.5 — insert — ambiguity — `decision_note` is type-checked but stored nowhere and appears in no response — `routes/delivery.py:118`
- 3.5 — insert — ambiguity — single reads of project/phase/reservation/permit/allocation/record are ownership-tested, but none of the root-level listings is narrowed to the caller's tenancy; the project-nested commissioning listing is the one that is — `routes/delivery.py:76-88,206-218,394-404`
- 3.6 — insert — ambiguity — optional ids resolved predecessor-then-amenity with their own 404s; amenity need not sit in the project's building — `routes/delivery.py:161-170`
- 3.6 — insert — ambiguity — a status-admitted package with null windows (blocked out of `DRAFT`) is passed over, not a conflict — `routes/delivery.py:238`
- 3.6 — revise — mismatch — a lease with `executed_at` still null fails `ERR_WINDOW_OUTSIDE_DELIVERY_TERM` for any window — `routes/delivery.py:274`
- 3.6 — revise — mismatch — the hold cascade suspends the project only from `C_IN_PROGRESS`; from `C_NOT_STARTED` it is not touched or bumped, though `delivery_risk` still reads `AT_RISK` — `cascades.py:32-34`
- 3.6 — insert — ambiguity — restoration is driven by `prior_status` alone, so a release restores blocked packages that also sit downstream of a still-held package — `cascades.py:45-49`
- 3.7 — insert — ambiguity — `headcount` consumed by no rule; ids resolve amenity-then-project; ownership test precedes the five domain rules — `routes/facilities.py:121-130,149`
- 3.7 — insert — ambiguity — the allocation under confirmation is withheld from the incumbent set and counted once as the candidate — `routes/facilities.py:184-185`
- 3.7 — revise — mismatch — cancel has **three** domain rules, not two; the future-window test is third, after the ownership test, and returns `ERR_INVALID_ALLOCATION_STATE` — `routes/facilities.py:197-201`
- 3.8 — revise — mismatch — `control_area_index` is an integer whose bounds are the first domain rule, so 0 or -1 yields `ERR_CONTROL_AREA_OUT_OF_RANGE`, not `ERR_VALIDATION`; ids resolve project-then-floor — `routes/facilities.py:232,239`
- 3.8 — insert — ambiguity — the decision ceiling is the permit's **own stored** `allowance_per_control_area_gal`, frozen from its own `use_condition` — `routes/facilities.py:310`
- 3.8 — insert — ambiguity — `APPROVE` leaves `decision_reason` null even when supplied — `routes/facilities.py:316-317`
- 3.9 — insert — ambiguity — `scheduled_for` stored as supplied, not required to be future; `construction_status` not consulted at scheduling — `routes/facilities.py:333-342`
- 3.9 — revise — mismatch — in the acceptance cascade the lease advances/bumps only from `EXECUTED`; the building is bumped exactly once, and not at all when no `RESERVED` reservation moved — `cascades.py:69-89`
- 3.9 — revise — mismatch — FAIL reversal covers the phases the draw actually paid across **every** project on the lease, not just the commissioned project; with `last_disbursement_usd` already 0 nothing moves and the lease is neither touched nor bumped — `cascades.py:93-110`
- 3.9 — revise — mismatch — settlement values liability off the permits *before* they are surrendered; the building is bumped once only if a reservation was released — `cascades.py:116,135-150`

Left unpinned by Pass C: six unreachable defensive branches (`lease is None`, `building is None`, `amenity is None`, `floor is None`, `committed < 0` clamp, `required > 0` guard) — not observable through the API; cycle protection in `queries.transitive_successors` (`predecessor_phase_id` is write-once); allocation windows not tested against the lease term (§3.7 already enumerates the booking's rules exhaustively); intra-request `version`-bump ordering (no response exposes it, §2.10 pins the final counts).

### Final artifact — orchestrator verification

- `PRD.md` 447 lines / 97,582 B -> `PRD_FINALIZED.md` 447 / 97,990 B -> `PRD_COMPLETED.md` 447 lines / **111,436 B** (+13.7 % bytes over FINALIZED, 0 % lines — every edit is an in-paragraph insert or revision).
- `cmp` confirms `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md`; `diff` reports **40 changed paragraphs**, so all three passes' edits are present and none clobbered another.
- Structure intact: 5 top-level sections (§1–§5), 19 subsections (ten §2.x + nine §3.x), §4 endpoint table **69 rows**, §5 error table **68 rows**, file ends at a real boundary (final §5 row `| `ERR_WITNESS_CONFLICT` | 403 |`), no mid-sentence truncation.
- `find` confirms **no file under `workspace/implementation/` was modified after the 08:25 green sweep**, so the verified 8×95/95 result still describes the shipped implementation.

Pipeline complete.
