# Worklog — task_0547_chimney_sweep

## Step 1: Create task directory — 2026-07-02T00:00:00.000Z

Created `tasks/task_0547_chimney_sweep/` and `tasks/task_0547_chimney_sweep/workspace/` (task_dir explicitly specified by user; index auto-scan skipped to avoid parallel ID contention). Difficulty: Expert.

## Step 2: Generate scaffold — 2026-07-03T03:16:42.000Z

Clean lint across all three files. Here is the summary of what I generated for `task_0547_chimney_sweep` (Expert difficulty).

## Scaffold overview

**Domain:** Chimney Sweep & Fireplace Service. Archetype: posture-driven gating + workflow orchestration; flat topology (peer collections linked by FKs, `api_prefix: "/"`); parallel-dimension state shape; peer roles; immediate consistency.

**§1.1 Entities (11):** Customer, Chimney, Technician, RouteDay, ServiceJob, Appointment, SweepLog (append-only), SafetyCheck (append-only), RepairOrder, Warranty, ReminderSchedule. ServiceJob carries two independent state dimensions (`job_status` × `safety_posture`) plus cross-entity computed ledger fields (`committed_cost_cents`, sweep provisional/final, `invoice_total_cents`).

**§1.2 State machines (7):** ServiceJob.job_status (linear w/ cancel-cascade), ServiceJob.safety_posture (threshold-derived, parallel dimension), RepairOrder (cyclic IN_PROGRESS↔BLOCKED), Appointment, Warranty, ReminderSchedule (ACTIVE self-loop recurrence). One §1.2.1 concurrency rule: OCC on `Chimney.version` for reminder supersede (`ERR_STALE_CHIMNEY_VERSION`, 412).

**§1.3 Calculations (7):** sweep_service_cost (tiered, provisional-vs-final variants), invoice_total (per-line disposal-fee rounding), warranty_claim_credit (LABOR_ONLY vs PARTS_INCLUSIVE proration), safety_posture_derivation (CO ppm thresholds), committed_cost (money invariant), routeday_booked_minutes (time invariant), reminder_next_due. All literal expected values pre-computed and verified in Python.

**§1.5 Endpoints:** 36 (CRUD + action/transition endpoints + filtered-list and sub-resource reverse-GETs for every FK + `/_clock/set_current_utc` with default `2026-05-01T00:00:00Z`).

**§1.6 Error catalog:** 33 error codes.

**§1.7 RBAC:** 3 roles — Dispatcher (opaque), Technician (entity_backed), BillingClerk (opaque).

## Design files
- **§1.8 difficulty design:** 18 instances = 9 rules × 2 (dual_variant_calc, combinatorial_formula [modes a+b], non_linear_state_machine, transitive_cascade [depth-3 job→appointment→routeday + depth-2 repair→committed_cost], priority_pair_validation_conflict [state-vs-safety, referential-vs-fiscal], boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap [buffer vs aggregate-capacity], compensating_invariant [money vs minutes]).
- **§1.9 corner design:** 31 active instances + 4 `excluded_because` stubs, spanning entities/state-machines/calculations/validations/endpoints/errors/cross-cutting sections.

**Lint verdict:** `clean lint` — 305 recipe calls conform to §1.5, all 11 FKs reverse-reachable, all OCC version inputs dynamic. All three files are valid YAML with the correct single top-level keys.

Files:
- SCAFFOLD.yaml (1110 lines)
- SCAFFOLD_DIFFICULTY_DESIGN.yaml (930 lines)
- SCAFFOLD_CORNER_DESIGN.yaml (1016 lines)

## Step 3: Copy INSTRUCTION.md — 2026-07-03T03:17:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-07-03T03:21:00.000Z

PRD generation completed (backfilled worklog entry — original record was lost when the run was interrupted before the log write). `workspace/PRD.md` fully generated: 296 lines / 42518 bytes, covering entities, dual-dimension state machines (job_status × safety_posture), calculations, validation/precedence rules, 36 endpoints, and the error catalog. Generated from `SCAFFOLD.yaml` only; both `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` withheld to prevent test-answer leakage into PRD prose.

## Step 5: Generate unit tests — 2026-07-03T03:40:00.000Z

Test infrastructure generation is complete. Here is the summary.

## What was generated

**`test_helpers/`** (Stage 1 — 9 files, PRD-specific infrastructure over the `prd_bench_local_runner.testing` framework):
- `types.py` — status enums + entity TypedDicts. `SweepLog`/`SafetyCheck` correctly omit `updated_at`/`version` (append-only logs, PRD §2.4); all others carry the full common-field set.
- `api_client.py` — one method per PRD endpoint (all 35 rows).
- `api_errors.py` — 32-error `ApiErrorId` enum + HTTP-status map registered via `set_error_http_status_map`.
- `factories.py`, `assertions.py`, `constants.py` (pricing tiers, CO thresholds, disposal rate, route-window timestamps).
- `test_users.py` — opaque `Dispatcher`/`BillingClerk` shared constants + `make_technician_headers(id)` for the entity-backed `Technician` identity threading.
- `fixtures.py` — composite setup helpers (safe-job, in-progress-job, completed-invoice-job with N repairs, warranty issuance, reminder/OCC), all threading the acting technician's id into ownership-gated appointment transitions.

**`test_suite/`** (Stage 2 — conftest + 8 domain-named files, **66 test functions**).

## Coverage (design-index-only)

- **Queue A (Difficulty):** all **18** instances (9 rules × 2) each carry **≥2** tests tagged `Design: Difficulty/<rule_id>/<name>`. Boundary CO test split into two functions so the ≥2 count is unambiguous.
- **Queue B (Corner):** **30 of 31** non-stub instances translated (1 test each, `Design: Corner/<section>/<name>`). The 4 `excluded_because` stubs were verified to cross-reference real difficulty instances and were **not** translated.

## One skip (genuine PRD gap, not papered over)

- `Corner/entities/system_fields_input_ignored_on_create_customer` — **skipped**. Its assertions (`version == 1`; client-supplied `id` ignored) are not uniquely PRD-derivable: §2.4 says version "starts at its initial value" without pinning `1`, and "server-minted identifier" does not commit to ignoring-vs-rejecting a client `id` field. Two faithful PRD-only implementers could diverge. For the same reason, `creation_success_customer` asserts 201 + submitted fields + valid-UUID id but not the non-derivable `version == 1`.

## Verification performed
- All 17 files byte-compile.
- Every Design tag maps to a real instance; no untagged/dual-tagged tests; no `skip`/`xfail`/`skipif` markers.
- Every verbatim PRD citation substring (~70) confirmed via literal `grep` of `workspace/PRD.md`, including bold-marker `**...**` precedence quotes from §2.11.
- No scaffold/table/§1.x leakage in emitted code; no hardcoded `version == 1`.
- Precomputed literal expected values copied verbatim from the design indices (e.g. sweep 27500/50500/53000, invoice 17869/15675, warranty credits 8000/11000, committed 35000→23000, booked-minutes 210→120).

Note: the framework package `prd_bench_local_runner` is not installed in this environment (the runner provides it), so tests were syntax-verified but not executed here.

## Step 6: Generate implementation — 2026-07-03T03:40:00.000Z

The implementation is complete and verified. Here is a summary.

## What was built

A complete Python + Flask REST API for the Chimney Sweep & Fireplace Service, in `workspace/implementation/`:

- `app.py` — single-file server (all 35 endpoints, in-memory store, no seeding)
- `start.sh` — foreground launcher with guarded `pip install` (imports flask check) and `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask

## Key implementation decisions (traceable to the PRD)

- **Response envelope**: exact `meta`/`response_type`/`data` shape from SCAFFOLD §1.0; pagination fields (`limit`/`offset`/`total_count`/`has_more`) in `meta` for lists; `limit` default 10, clamped [1,100], sort by insertion order (= `created_at` asc).
- **Auth**: `X-User-ID`/`X-User-Role`; Technician role is entity-backed (identity match on appointment transitions → `ERR_TECH_IDENTITY_MISMATCH`), Dispatcher/BillingClerk opaque. Per-action role restrictions on both transition endpoints enforced before existence to honor precedence.
- **Validation precedence** follows PRD §2.11 (auth → role → identity → path/FK existence → shape → state → temporal → safety → part → scheduling → fiscal → OCC). For job completion I used §2.11's explicit precedence (`ERR_JOB_HAS_OPEN_REPAIRS` before `ERR_JOB_UNSAFE`), which is the authoritative precedence section over §3.6's narrative order.
- **Calculations** use `Decimal` + `ROUND_HALF_UP`: tiered sweep pricing (provisional vs final variants), invoice disposal fee rounded **per line before summing**, warranty claim proration with floored calendar-month elapsed, custom `add_months`/`months_between` (Python 3.9's `fromisoformat` can't parse `Z`, so a regex ISO parser is used).
- **Parallel state machines**: `job_status` and `safety_posture` tracked independently; CONDEMNED terminal; CO thresholds inclusive at 9/70.
- **Cascades & invariants**: `booked_minutes` and `committed_cost_cents` recomputed from surviving records (bumping `version`/`updated_at`); job-cancel cascade releases appointment minutes, cancels open repairs, voids ISSUED+CLAIMED warranties.
- **OCC**: `expected_chimney_version` vs `Chimney.version`; reminder create supersedes prior ACTIVE and bumps chimney version.
- **Logical clock**: module-level default `2026-05-01T00:00:00Z`, resets on every fresh boot (critical for `--isolation per-test-server`).

## Verification

Booted from a fresh process and ran a full end-to-end smoke test (onboarding → job → appointment lifecycle → sweep/safety → repair → completion → warranty claim → reminder OCC). All computed values matched expectations (27500, 50500, 63223, 7000) and all error paths returned the correct error IDs and HTTP statuses.

## Step 7: Run tests and iterate (RESUME) — 2026-07-03T04:00:00.000Z

Resumed Step 7 as the long-lived diagnostic subagent. Deleted all prior `results.*.json` and re-ran a fresh parallel 8-round stability sweep under `--isolation per-test-server`. **All 8 rounds returned passed 67 / total 67 / failed 0 / errors 0** — the union of failing tests across all 8 rounds is empty. The prior sweep's failures (`test_complete_repair_from_proposed_rejected`; solo-round `test_committed_cost_before_and_after_repair_cancel`) did NOT reproduce.

Subagent summary (verbatim): "All 8 parallel rounds passed 67/67 clean. No failures in the union set, so no diagnostic protocol or fixes were needed. Iterations run: 1. Tests deleted: none. Fixes applied to test_helpers/: none. Fixes applied to implementation/: none."

Orchestrator verification & note: independently re-ran a 4-round parallel confirmation sweep (correct `cd $IMPL && bash start.sh` start-command) — all 4 rounds 67/67 clean, for 12 total green rounds. (An initial confirmation attempt using a *relative* `bash start.sh` start-command produced all-tests-ERROR because the runner resets cwd to project root before each per-test server restart; corrected to the absolute cd form.) `app.py` carried an 11:52 mtime — *after* the prior failing sweep (11:50) — indicating the prior interrupted session had already applied the Step 7 implementation fix (repair-order state machine: COMPLETE legal only from IN_PROGRESS → `ERR_INVALID_STATE_TRANSITION`, per PRD §3.5; committed_cost recomputation on repair cancel/reject, per PRD §2.8) before the interruption; the resume sweep verifies that fix as stable. Because a real Step-7 implementation fix exists (even though 0 changes this resume session), Step 8 is NOT skipped. Canonical final sweep: `results.{1..8}.json` (all 67/67).

## Step 8: Finalize PRD — 2026-07-03T04:05:00.000Z

Result: zero edits. Both Step 7 focus sites were already uniquely determined by existing PRD prose; `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md` (296 → 296 lines, 0.0% delta).

Subagent summary (verbatim):
- Focus 1 — RepairOrder COMPLETE / source-state gating: PRD §3.5 already pins "Each of these transitions is legal only from the state named as its source; any other origin is `ERR_INVALID_STATE_TRANSITION`." COMPLETE's named source is IN_PROGRESS, so completing a PROPOSED order → ERR_INVALID_STATE_TRANSITION, matching impl app.py:1095. No silence/mismatch.
- Focus 2 — committed_cost_cents recompute on CANCEL/REJECT: PRD §2.8 states the formula verbatim; §3.5 covers accept/reject/cancel recompute; §3.9 the job-cancel cascade. Example figures 15000→35000→23000 follow from the formula. Matches impl committed_value/recompute_committed (app.py:403-415) and callsites (1017, 1070, 1108, 810). No silence/mismatch.
- Pre-edit enumeration performed for both subjects (repair_transition handler app.py:1042-1109 per-action source states; committed_cost helpers + all callsites incl. cancel_job cascade); no wording adjustment required.

## Step 9: Complete PRD — 2026-07-03T04:12:00.000Z

Full PRD-vs-implementation completeness scan. `PRD_COMPLETED.md` = `PRD_FINALIZED.md` + 8 in-paragraph edits (5 ambiguity-pins, 3 mismatch-revisions); 296 → 296 lines, 42,518 → 43,638 chars (+1,120).

Subagent summary (verbatim):
- §2.4 — revise — ambiguity — `version` "starts at its initial value" pinned to "starts at 1" — app.py:201
- §2.8 — revise — mismatch — recompute only bumps version/updated_at when the aggregate actually changes (no-op recompute is a no-op) — app.py:397-400, 411-415
- §2.3 — insert — ambiguity — out-of-range limit/offset clamped (1..100, offset≥0) not rejected; non-integer → ERR_VALIDATION — app.py:354-372
- §3.3 — revise — ambiguity — on_site_minutes derivation pinned to integer/floor division discarding sub-minute remainder — app.py:852
- §3.4 — insert — ambiguity — inspect/sweep/safety-check permitted regardless of job_status (no lifecycle gate) — app.py:637-717
- §3.5 — revise — mismatch — provisional_cost_cents folded into committed at proposal/creation (PROPOSED already counts; approval changes nothing), not "on acceptance" — app.py:1006-1017, 403-408
- §3.6 — insert — ambiguity — null sweep_final_cost_cents (no sweep logged) contributes no invoice line — app.py:740-741
- §3.7 — insert — ambiguity — repair order not belonging to named job → ERR_REPAIR_ORDER_NOT_FOUND at FK-existence stage before COMPLETED/safety gates — app.py:1126-1127

Pipeline complete. Final state: 12 green sweep rounds (8 canonical results.{1..8}.json + 4 confirmation) at 67/67; PRD.md → PRD_FINALIZED.md (0 edits) → PRD_COMPLETED.md (8 edits).
