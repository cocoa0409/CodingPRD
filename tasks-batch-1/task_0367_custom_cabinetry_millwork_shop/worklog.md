# Worklog — task_0367_custom_cabinetry_millwork_shop

## Step 1: Create Task Directory — 2026-06-15T02:34:05.000Z

Task directory `tasks/task_0367_custom_cabinetry_millwork_shop` was pre-allocated. Ensured `workspace/` subdirectory exists. No auto-numbering scan performed (task ID fixed by orchestrator instruction).

## Step 2: Generate Scaffold (Expert difficulty) — 2026-06-15T02:55:05.000Z

Generated all three Expert-difficulty scaffold artifacts for `task_0367_custom_cabinetry_millwork_shop`, lint-clean against the skill's own `scaffold_lint.py` (`VERDICT: clean lint`, 640 calls / 13 entities verified).

**Files written** (all absolute under `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0367_custom_cabinetry_millwork_shop/`):
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Scaffold contents (Expert band):**
- **13 entities**: Shop, Customer, Project, CabinetSpec, Material, MaterialReservation, Machine, BuildJob, FinishSelection, Draw, ChangeOrder, Installation, PunchItem. Hybrid topology (shop→customer→project tree + cross-aggregate FKs BuildJob→Machine, MaterialReservation/CabinetSpec→Material).
- **6 state machines**, several non-linear: Project (cyclic change-order loop + branching cancel paths), ChangeOrder (SUBMITTED↔REVISING cycle), Installation (punch reopen loop), plus Draw, MaterialReservation, BuildJob.
- **6 calculations** with non-trivial rounding/precedence: `cut_list_sheets` (pinned ceil-per-spec-then-sum), `contract_total` (tiered margin × qty-tier + finish bps + min/max clamp + rush + tax, estimate-vs-final dual variant), `material_consumption` (provisional-vs-actual dual variant), `draw_amount` (waterfall min-cap, deposit/progress/retainage variants), `draw_settlement` (circular-looking tiered late fee with pinned eval order), `change_order_delta` (signed margin/finish/tax pipeline). All assert literals computed in code.
- **17 ordered validations**, **28 errors**, **5 roles** (peer_roles: ShopAdmin opaque superset, ShopManager, Designer, Customer entity_backed, Installer), **1 OCC concurrency rule** (change-order-submit-stale-project on Project.version).
- **99 endpoints** (nested business action paths + flat top-level read aliases giving FK reverse-reachability for all 13 entities; `api_prefix: ""`).

**Difficulty index (§1.8):** all 9 rules × 2 = **18 instances**, each grounded in §1.1–§1.7, with executable `setup_api_calls`/`trigger` chains and pre-computed literal asserts.

**Corner index (§1.9):** **42 instances** across all 9 claim-extraction sections (39 active + 3 `excluded_because` stubs, each citing a valid §1.8 instance). All 60 instance names unique across both design files.

**Note:** the shipped example scaffolds predate the mandatory `identity:` RBAC field; followed the current SKILL.md (every role declares `entity_backed:<Entity>` or `opaque`). One YAML-syntax fix was needed (optional `field?` and `errors[...]` tokens quoted inside flow sequences). No sibling tasks were inspected.

## Step 3: Copy Shared Files — 2026-06-15T02:55:26.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0367_custom_cabinetry_millwork_shop/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-15T03:02:06.000Z

Generated `workspace/PRD.md` from the Expert-tier Custom Cabinetry & Millwork Shop scaffold.

**Document shape**
- 339 lines, 5 top-level sections, 20 subsections (10 in §2, 10 in §3).
- §2 (precise zone): 2.1 RBAC, 2.2 verbatim envelope, 2.3 pagination, plus 7 domain cross-cutting subsections (common properties/identity, nested path validation, money & rounding, OCC, hierarchical/cascade consistency, material stock ledger, billing ledger & fiscal guards).
- §3 (scattering zone): 10 lifecycle-driven subsections (shop setup, customers/intake, specs/cut-list/estimate, pricing, design-to-contract, reservations/build jobs, change orders, draws/settlement, install/punch, close/cancel).
- §4: 99-row endpoint table (4 columns). §5: 28-row error table (2 columns).

**Hard Contracts — all PASS**
- Contract 1 (Field-Name Coverage): 64/64 entity fields, 50/50 endpoint-input + OCC identifiers present in backticks, 0 missing.
- Contract 2 (Rule Coverage): all 28 errors, 26 state values, enum values, 5 roles, and every calculation constant present. OCC rule fully specified (`expected_project_version` + `ERR_STALE_VERSION` + 412). Dual-variant calcs rendered with symmetric density. Validation priority order expressed as an explicit ordered chain in the §4 preamble.
- Contract 3 (§3 Path Purity): 460 §3 backtick tokens scanned, 0 slash-paths, 0 bare methods, 0 method+path combos.

**Coverage decisions**
- ceil-per-spec-then-sum cut-list rule and per-step round-half-up pricing pipeline translated into precise prose.
- change-order BULK-tier-only delta + sign-preservation, waterfall billing cap, late-fee floor-days/tier selection (1–30 → 150 bps, >30 → 400 bps), and issue/void ledger conservation each given explicit sentences.
- §4 intro encodes the full 17-rule validation precedence.

Constraint honored: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

## Step 5: Generate Unit Tests — 2026-06-15T03:25:42.000Z

**Note on execution:** The first unit-test subagent hit an API socket error (connection closed unexpectedly) after 36 tool uses. It had written the full `test_helpers/` infrastructure and the queue-A (Difficulty/depth) tests (24 functions, all `Design: Difficulty/...`), but died before emitting ANY queue-B (Corner/breadth) tests. SendMessage to resume the dead agent was unavailable in this environment, so a second subagent was spawned to COMPLETE the suite (audit queue A, generate queue B) reusing the existing helpers. Combined result below.

**Outcome:** Queue B fully generated; queue A audited and confirmed complete. All `test_helpers/` and `test_suite/` files pass `python3 -m py_compile`.

### Test files (6 total in `test_suite/`)
- Queue A (untouched): `test_01_pricing_calculations.py`, `test_02_workflows_and_cascades.py`, `test_03_guards_and_boundaries.py`
- Queue B (new): `test_04_entities_and_lifecycle.py`, `test_05_calculations_and_validations.py`, `test_06_access_and_concurrency.py`

### Test functions: 63 total
- Queue-A existing: **24**; Queue-A added: **0**; Queue-B added: **39**. Disk-verified: 24 Difficulty tags + 39 Corner tags = 63.

### Queue A audit (SCAFFOLD_DIFFICULTY_DESIGN.yaml — 18 instances)
All 18 non-stub difficulty instances already have a matching `Design: Difficulty/<rule_id>/<instance.name>` test. Nothing missing → 0 added, 0 skipped. (8 of 18 carry only 1 test rather than the ideal ≥2, but every instance has ≥1 matching function.)

### Queue B generation (SCAFFOLD_CORNER_DESIGN.yaml — 42 instances)
- **39 non-stub instances translated → 39 tests** (1:1). By section: entities 11, state_machines 8, calculations 2, validations 4, errors 4, rbac 4, cross_cutting_complexity_layers 4, endpoints 1, consistency_model 1.
- **3 `excluded_because:` stubs NOT translated** (correct); all 3 difficulty cross-refs resolve to real difficulty instances.
- **0 non-stub instances skipped** — all passed the PRD-first two-condition filter (verbatim PRD coverage + unique derivability), cited PRD sentences confirmed by literal grep.

### test_helpers/ extensions (consistent with PRD prose)
- `test_users.py`: added `make_unknown_role_headers(...)` for the unknown-role rejection test (role outside PRD §2.1's five roles).
- `fixtures.py`: added `add_punch_item(...)` shared creator reused by three install/punch corner tests.
- `__init__.py`: re-exported `make_unknown_role_headers`.
- No new factories/assertions/constants required.

### Integrity checks
- Every new test docstring ends with exactly one verbatim `Design: Corner/<section>/<instance.name>` line; no untagged/dual-tagged tests. Emitted Corner tags diff exactly equal to the 39 non-stub instance names.
- `python3 -m py_compile` clean across all 9 helper + 7 suite files.

## Step 6: Generate Implementation — 2026-06-15T03:25:42.000Z

Built a complete Python + Flask in-memory REST API in `workspace/implementation/`. Server boots cleanly from a fresh process via `start.sh` with an empty store (no seeding). Smoke-tested (full design-to-install lifecycle, money math, change-order revision loop, OCC race, late-fee settlement, rush surcharge, ledger conservation, error paths, envelope structure).

**Files created (21 total):**
- `start.sh` (guarded pip install + `exec python3 app.py`), `requirements.txt` (flask 3.0.3)
- Foundation: `app.py`, `db.py` (in-memory store + helpers), `errors.py`, `response.py`, `middleware.py` (auth + RBAC), `helpers.py` (validation/pagination/rounding), `models.py` (records + computed-field serialization), `lookups.py` (path resolution + ownership), `services.py` (cascade side effects), `calculations.py` (6 calc rules)
- Routes: `routes_shop.py`, `routes_customer.py`, `routes_project.py`, `routes_spec.py`, `routes_production.py`, `routes_changeorder.py`, `routes_draw.py`, `routes_install.py`, `routes_flat.py`

**Endpoints: 99 route handlers**, covering every entry in PRD §4 (all nested action paths + flat single-resource/FK-filtered list aliases).

**Notable design decisions:**
- Computed fields derived on read, not stored (`reserved_sheets`/`available_sheets`, `billed_to_date_cents`/`paid_to_date_cents`/`open_change_delta_cents`, `lifetime_paid_cents`); mutations still bump parent `version`/`updated_at` per §2.8.
- Decimal-based `round_half_up` for all bps math; ceil-per-spec-then-sum cut list.
- Validation precedence per PRD §4: auth → role → ownership → existence (left-to-right) → body → state → cross-shop → domain → OCC. Existence before ownership for nested resources (nonexistent → 404, existing-but-unowned → 403).
- Change-order approve creates a PROGRESS adjustment draw for `max(0, delta_cents)` with the waterfall cap.
- Pure in-memory storage (single `Store()` at module load); no file/SQLite persistence, no startup seeding.

## Step 7: Run Tests and Iterate — 2026-06-15T04:05:00.000Z

(Resumed run. Step 7 had not been confirmed green across all 8 rounds before the interruption; the last on-disk sweep showed 7 rounds at 63/63 and one round at 62/63 with a load-induced boot transient. One long-lived fix subagent re-ran the full 8-round parallel per-test-server sweep after deleting stale results.)

All 8 rounds passed 63/63. The previous round-7 failure was indeed a pure environmental transient (boot-headroom / connection-aborted under 8× concurrent load), not a domain or logic problem. The clean sweep at the default `--timeout 120` confirms no code or test changes were needed.

Summary:

- Iterations run: 1 (one 8-round parallel sweep).
- Final sweep status: all 8 rounds passed=63/total=63.
- Tests deleted: none.
- Fixes applied to `test_suite/`: none.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `implementation/`: none.
- `--timeout` change for boot headroom: none. The prior round-7 failure (`requests.exceptions.ConnectionError: Connection aborted / BadStatusLine` on a setup-phase `POST /shops/.../customers` in `test_finish_selection_supersede_deactivates_prior`) was a pure transport transient from a load-induced boot-timeout under the 8×-concurrent per-test-server restart load, not a domain assertion failure. The resumed clean sweep reproduced zero failures of any class at the existing `--timeout 120`, so no headroom increase was required.

Notes:
- start.sh (`tasks/task_0367_custom_cabinetry_millwork_shop/workspace/implementation/start.sh`) already uses a guarded pip-install (`if ! python3 -c "import flask"`) followed by `exec python3 app.py`, with no unconditional install — correct boot behavior for repeated per-test-server reboots.
- Stale `results.*.json` were deleted before the run; the 8 fresh result files now sit under `tasks/task_0367_custom_cabinetry_millwork_shop/workspace/implementation/`.

## Step 8: Finalize PRD — SKIPPED — 2026-06-15T04:08:00.000Z

Skipped per the SKILL.md Step 8 skip condition. Step 7 exited with **0 tests deleted, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes** — i.e. zero iterations beyond the baseline; the Step 6 implementation passed the full 8-round sweep clean as generated. Therefore `PRD.md` already uniquely determines every behavior the implementation exhibits at the Step 7 fix sites (there are none), and no `PRD_FINALIZED.md` is produced. The Step 8 subagent was not spawned. Step 9 will start its completeness scan from `workspace/PRD.md`.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-15T04:20:00.000Z

Source file: `PRD.md` (PRD_FINALIZED.md absent this run) → `PRD_COMPLETED.md`
- Line counts: 339 → 339 (unchanged)
- Char counts: 57,358 → 59,420 (delta +2,062)

Counts: ambiguity-pins = 5, mismatch-revisions = 3 (8 edits total)

Per-change bullets:

- **§2.1 (Customer ownership)** — insert — ambiguity — Pinned that the customer ownership check ALSO guards the nested project-scoped reads of draws and change orders (get/list under `/shops/{shopId}/projects/{projectId}/draws` and `/change-orders`), returning `ERR_NOT_RESOURCE_OWNER` for non-owned projects, while flat single-resource and FK-filtered list reads are NOT ownership-gated for any role including Customer — `routes_draw.py:43-45,49-54` (get/list draw call `require_project_owner`), `routes_changeorder.py:41-48,51-57` (get/list CO call `require_project_owner`), vs `routes_flat.py:244-268,274-295` (flat draw/CO reads have no owner check).

- **§3.1 (Shop config, `change_order_buffer_pct_bps`)** — revise — mismatch — PRD said the field "is kept at 0"; impl actually defaults it to 0 but accepts any client-supplied value ≥ 0 with no upper bound. Revised to "defaults to 0 and is bounded to a minimum of 0 with no upper bound." — `routes_shop.py:32`.

- **§3.1 (Material `sku`)** — revise — mismatch — PRD claimed `sku` is "unique within the shop"; impl performs no uniqueness check and accepts duplicates. Revised to state uniqueness is not enforced. — `routes_shop.py:75-94` (no uniqueness check in `create_material`).

- **§3.2 (Customer `email`)** — revise — mismatch — PRD claimed `email` is "unique within the shop"; impl performs no uniqueness check and accepts duplicates. Revised to state uniqueness is not enforced. — `routes_customer.py:15-32` (no uniqueness check in `create_customer`).

- **§3.3 (Cut-list response shape)** — insert — ambiguity — PRD described only the per-material `total_sheets`; impl returns an object `{"materials": [{material_id, total_sheets}, ...], "total_sheets": <project-wide sum>}`. Pinned the full response shape including the top-level project-wide `total_sheets`. — `routes_project.py:98-104` and `calculations.py:57-69`.

- **§3.7 (ChangeOrder creation state & initial `delta_cents`)** — insert — ambiguity — (a) PRD framing implied creation requires `IN_PRODUCTION`; impl imposes no project-status precondition on create (the gate is only at submit). (b) PRD said `delta_cents` "is set when submitted" but was silent on its pre-submit value; impl stores `null` until submit. Pinned both. — `routes_changeorder.py:19-38` (create has no status check; `delta_cents` initialized to `None`).

- **§3.8 (On-demand draw creation)** — insert — ambiguity — PRD framed the on-demand endpoint as creating "progress draws"; impl accepts any `draw_type` of DEPOSIT/PROGRESS/RETAINAGE and imposes no project-status precondition, with the new draw starting PENDING. Pinned. — `routes_draw.py:18-36` (`require_enum` accepts all three types; no state guard).

- **§3.8 (Progress draw `requested_pct_bps` default)** — insert — ambiguity — PRD called `requested_pct_bps` "optional" but was silent on the omitted case; impl defaults it to 0, yielding raw amount 0 and `amount_cents` 0. Pinned. — `routes_draw.py:26-27` (`default=0`) and `calculations.py:131-132`.

- **§4 (Validation precedence, ownership vs existence)** — insert — ambiguity — PRD §4 listed ownership (priority 3) strictly before path existence (priority 4), but the ownership check is evaluated against the owning Project, so impl always resolves shop+project existence before the ownership comparison. Added a clarifying clause that the shop and project path identifiers are resolved for existence before ownership is evaluated. — `routes_draw.py:43-45,89-95`, `routes_changeorder.py:45-47,95-97,124-126,150-152` (`get_project_in_shop` precedes `require_project_owner` in all customer-actor endpoints).
