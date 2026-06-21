# Worklog — task_0405_nemt_medical_transport

## Step 1: Create Task Directory — 2026-06-18T12:26:03.000Z

Task directory `tasks/task_0405_nemt_medical_transport/` was pre-allocated by the user (with `workspace/` subdir already present). No auto-increment scan performed; used the assigned directory directly. Scenario: Non-Emergency Medical Transport (NEMT, ModivCare style). Step 2 scaffold to be generated at **Expert** difficulty (this difficulty requirement applies to scaffold-generator only).

## Step 2: Generate Scaffold (Expert difficulty) — 2026-06-18T12:47:22.000Z

Generated all three Expert-tier scaffold artifacts at `tasks/task_0405_nemt_medical_transport/`. All produced purely from the scenario + skill spec (no sibling tasks consulted). **`scaffold_lint.py` returns `VERDICT: clean lint`** (491 calls scanned across 18+28 instances; all FKs reverse-reachable). File sizes: SCAFFOLD.yaml 1371 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1334 lines, SCAFFOLD_CORNER_DESIGN.yaml 1283 lines.

**SCAFFOLD.yaml** (§1.0–§1.7)
- **Archetype**: ledger_reconciliation + selector_policy; layers: dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency. Topology flat; state shape parallel; role model peer_roles.
- **11 entities**: Member, EligibilitySpan, Broker, Driver, RateSchedule, TripRequest (hub), Leg, Assignment, StandingOrder, Claim, Encounter. 14 FKs, all with reverse-reachability GETs.
- **6 state machines**: Member eligibility (ELIGIBLE↔SUSPENDED→TERMINATED), Broker, Driver, TripRequest **dual parallel axes** (trip_status lifecycle × billing_status reconciliation), and Leg with a **cyclic will-call** sub-lifecycle (PENDING↔READY).
- **7 calculations**: `claimed_cost_forward` (forward, sum-then-round) vs `encounter_cost_chronological` (chronological, round-per-leg) — the core dual-variant divergence; `deadhead_billing` and `will_call_dwell` (strict-`>` threshold); `reconciliation_variance` (DISPUTED routing at 500c tolerance); `noshow_strike_accrual` (≥3 auto-suspend); `standing_order_generation` (idempotent rolling-horizon).
- 1 OCC concurrency rule (`trip-assign-stale-version`, 412), 16 ordered validations, 16 errors, 5 roles (Driver entity_backed), 54 endpoints (incl. 2 `/_` test-driving: clock + county-distance).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8): all 9 rules × 2 = **18 instances**, each with executable `setup_api_calls`/`trigger` chains. Key computed literals verified by code: claimed 7000c vs encounter 7780c (variance 780→DISPUTED), reconciled-path variance 100c, deadhead 560c (=(12−5)×80) vs raw-12 boundary at exactly-5→0c, dwell boundary exactly-10min→0.

**SCAFFOLD_CORNER_DESIGN.yaml** (§1.9): **28 active + 5 excluded_because stubs** across all 9 guide sections (CRUD/required-field/enum/FK-422/not-found, invalid transitions, terminate-dependency, bubble-up completion, dispute-override, no-show→auto-suspend, standing-order weekday-mask + idempotency + pause-suppression, RBAC denials/401/not-owner, OCC stale-version 412 + version-bump, immediate consistency). All stub references resolve to named §1.8 instances; all 51 names unique.

Key fix applied during generation: inserted clock-set-to-09:00 before each will-call `ready` so `ready_called_at`/`picked_up_at` sit on a consistent timeline matching the asserted dwell literals.

## Step 3: Copy INSTRUCTION.md — 2026-06-18T12:47:22.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0405_nemt_medical_transport/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-18T12:54:04.000Z

PRD generated at `workspace/PRD.md` (274 lines). Design files (DIFFICULTY/CORNER) NOT read, per hard constraint.

**Structure:** 5 top-level sections, 20 subsections.
- §1 Introduction (broker-in-the-middle business context; dual status axes + intentional dual-variant costing)
- §2 Global Specifications — 10 subsections: RBAC, fixed §2.2 envelope, pagination, identity/versioning, hierarchical cascades, nested-path validation, modality/LoS/county ordering, OCC-on-assignment, monetary/temporal precision, validation-ordering
- §3 Business Logic — 10 subsections by lifecycle stage (members/eligibility, brokers/drivers/rates, trip creation+scheduling, assignment+dead-head, leg execution+will-call, standing orders, forward claim, encounter, reconciliation, test-driving)
- §4 endpoint table (all 54 endpoints), §5 error table (all 16 errors)

**Notable scattering / zero-silence decisions:**
- Two cost variants deliberately split: round-half-up-once-at-end (forward claim, §3.7) vs round-per-leg-then-sum (encounter, §3.8) divergence stated explicitly as "the engine of reconciliation variance," both rounding points spelled out.
- Assign-endpoint params scattered: core selection §3.4, `expected_trip_version` OCC in §2.8 (framed as stale-version, never a race), `preferred_broker_id` in §3.4.
- Constants in prose: no-show threshold "three or more strikes," variance tolerance "500 cents," strict `>` boundaries for dead-head free miles and dwell free minutes ("exactly equal ⇒ 0").
- Validation priority (§2.10) rendered as explicit ordered list with eligibility-before-fiscal precedence.
- Two immutable entities (EligibilitySpan, RateSchedule) flagged as id/created_at only — no updated_at/version.

**Contract reports (PASS):** Field coverage 66/66; Rule coverage all expressed (validations w/ priority, OCC, 6 state machines, 6 calcs incl. divergent rounding, cascades, defaults, sibling-branch symmetry); Path purity §3 — 388 backtick tokens scanned, 0 paths/methods.

## Step 5: Generate Unit Tests — 2026-06-18T13:19:09.000Z

Generated `test_helpers/` (9 files) + `test_suite/` (conftest + 8 domain-named files).

**Stage 1 — `test_helpers/`** (9 files): `types.py` (entity TypedDicts; EligibilitySpan and RateSchedule carry only `id`+`created_at`, no `version`/`updated_at`), `api_client.py` (one method per PRD endpoint incl. `/_clock/set` and `/_geo/county_distance`), `api_errors.py` (15 error IDs), `assertions.py`, `factories.py` (input-only), `constants.py`, `test_users.py` (opaque Coordinator/Broker/Auditor + entity-backed Driver with `make_driver_headers`), `fixtures.py` (composite world-builder + lifecycle helpers for one-way/round-trip/will-call/claim-encounter-reconcile/no-show chains), `__init__.py`.

**Counts:** **68 tests total** — **36 queue A (Difficulty)** + **32 queue B (Corner)**. All 8 files compile; no skip/xfail; every test has exactly one verbatim `Design:` tag.

**Coverage:** Queue A — all 18 difficulty instances (9 rule_ids × 2) covered by ≥2 tests each. Queue B — all 28 non-stub corner instances covered by ≥1 test; 5 `excluded_because:` stubs not translated (cross-refs resolve to real difficulty instances). **Instances skipped for PRD coverage / unique-derivability: none.**

**Notable adjudication calls:**
- Dual-variant/boundary dead-head instances assert the observable raw `Assignment.deadhead_miles` (PRD 3.4 "stored on the assignment as `deadhead_miles`"); billable charge not a serialized field, so not asserted.
- `reconcile_without_encounter` and `duplicate_claim` use `validate_error_is_one_of([ERR_RECON_INCOMPLETE, ERR_INVALID_STATE])` per corner design's own set assertions (PRD does not commit to which guard fires first).
- One citation corrected from endpoint-titular table-row quote (C2 violation) to rule-bearing PRD 2.3 + 3.4 prose.

## Step 6: Generate Implementation — 2026-06-18T13:19:09.000Z

Built Python + Flask in-memory REST API at `workspace/implementation/`. Impl-gen self-reported all 68 tests passing under per-test-server isolation across two runs (~41s each) — Step 7's authoritative 8-round parallel sweep still to run.

**Files:** `start.sh` (guards pip install on `import flask` check, then `exec python3 app.py`), `app.py` (7 blueprints, uniform error handlers, binds 0.0.0.0:$PORT default 10000, threaded), `db.py` (11 entity dicts + county-distance matrix, UUID/ts/version helpers, monotonic `_seq` insertion counter; starts empty, no seeding), `clock.py` (settable logical clock, ISO-8601-UTC 3-digit fractional), `errors.py`, `response.py`, `middleware.py`, `helpers.py`, `serializers.py`, `routes/` (members, providers, trips, legs, standing_orders, billing, testdrive), `services/` (cascades, calculations, eligibility).

**Key design:**
- State machines: TripRequest dual axes (`trip_status` × `billing_status`); cascades bump `updated_at`/`version` on each touched resource.
- Dual-variant calc: `claimed_cost_forward` sum-then-round; `encounter_cost_chronological` round-per-leg-then-sum, replaying DROPPED_OFF legs in `dropped_off_at`/`created_at` order. Verified 7000 vs 7780 → variance 780 → DISPUTED → override → RECONCILED.
- Strict `>` boundaries for deadhead free-miles and will-call dwell; `>=` for no-show auto-suspend at 3.

**Two PRD-tension resolutions:**
1. Broker claim ownership: PRD 3.7 says claiming broker must be assigned broker, but PRD 2.1 (authoritative) says Broker `X-User-ID` is opaque, never matched against stored records. Check only fires when supplied id maps to a real Broker row; opaque ids pass (entity-backed ownership = Drivers only).
2. Assign error precedence: already-ASSIGNED trip returns `ERR_ASSIGNMENT_EXISTS`; DRAFT trip returns `ERR_INVALID_STATE` (single-active-assignment check before SCHEDULED-state check).
- Insertion-order `_seq` tiebreak needed for selection/list ordering under frozen test clock (shared `created_at`).

## Step 7: Run Tests and Iterate — 2026-06-18T13:22:21.000Z

First 8-round parallel stability sweep was already fully green: every round reported `passed == total == 68` with `failed=0`, `errors=0`, `skipped=0`. Orchestrator independently re-verified all 8 `results.{1..8}.json` files: round 1–8 each 68/68 passed, 0 failed/errors/skipped.

(Subagent note: its very first analysis query mistakenly keyed on a nonexistent `outcome` field instead of the real `status` field, momentarily making every test look like a failure; once it used the correct `status` key, all 8 rounds confirmed clean. No code or test was touched on that false signal.)

- **Iterations run beyond baseline:** 0
- **Tests deleted:** 0 (no PRD-silence or unique-derivability failures encountered)
- **Fixes applied to `test_helpers/`:** 0
- **Fixes applied to `implementation/`:** 0

The 68 tests span all 8 test files (CRUD, RBAC, scheduling/eligibility, assignment/deadhead, legs/will-call, billing/costs, cascades/lifecycle, standing orders). Passing deterministically across all 8 concurrent rounds.

## Step 8: Finalize PRD — SKIPPED — 2026-06-18T13:22:21.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes (zero iterations beyond baseline). `PRD.md` already determined every behavior the implementation exhibits, so no `PRD_FINALIZED.md` is produced. Step 9 will start from `PRD.md`.
