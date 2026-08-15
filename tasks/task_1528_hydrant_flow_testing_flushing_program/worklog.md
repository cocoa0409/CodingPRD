# Worklog — task_1528_hydrant_flow_testing_flushing_program

## Step 1: Create task directory — 2026-08-13T18:08:00.000Z

Pre-assigned task directory `tasks/task_1528_hydrant_flow_testing_flushing_program/` and its `workspace/` subdirectory verified to exist (created by the pipeline launcher). No index scan performed per instructions.

## Step 2: Generate Scaffold — 2026-08-13T19:04:02.693Z

Scaffold generated and lint-clean at `/home/ubuntu/github/CodingPRD/tasks/task_1528_hydrant_flow_testing_flushing_program/` (three files: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`). No sibling tasks were read; the design is purely from the scenario plus the skill spec.

Lint verdict (verbatim):
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared: 57 · §1.1 entities: 12 · §1.8 instances: 20 · §1.9 instances scanned: 51 · calls scanned: 506
```

## Summary

**Profile**: compliance_audit × temporal_windowing; layers: optimistic_concurrency, cascading_side_effects, rate_threshold_triggers, derived_field_reconciliation; flat topology; cyclic state shape; segregation_of_duties role model; immediate consistency; logical clock default 2026-08-01T00:00:00Z.

**Entities (12)**: FlushingProgram, PressureZone, PrivateOwner, Hydrant, Inspection, FlowTest, FlushSequence (embedded valve-step array), WaterQualityComplaint, HydrantOutage (embedded fire-dept notification), RepairWorkOrder (embedded part lines), Part, ISOSnapshot.

**State machines (9)**: cyclic Hydrant IN_SERVICE⇄OUT_OF_SERVICE; Inspection with REJECTED→PENDING_VERIFICATION resubmit loop; FlowTest with REJECTED/MISSED→SCHEDULED retest loops plus system MISSED transition; branching FlushSequence (COMPLETE vs ABORT with compensation); RepairWorkOrder SUBMITTED→DRAFT revision loop; guarded transitions everywhere (program OPEN, hydrant IN_SERVICE, no-open-WO on outage close, notification acked).

**Calculations (10)**: NFPA-style pitot flow → flow-at-20psi chain (exponent 0.54, strict residual > 20 gate, `>=` PASS boundary); dual-variant provisional-vs-approved hydrant fire flow; per-step-rounded flush volume (pinned rounding order) chaining into ceiling-based dechlorination tablets; inspection due-tier thresholds (CURRENT/DUE_SOON/OVERDUE/CRITICAL at exact boundary dates); complaint cluster >= 3 in rolling 72 h auto-creating targeted flush sequences; quoted-vs-actual work-order totals with pinned evaluation order (discount tier on subtotal, fee tier on discounted total — circular-looking dependency resolved); weighted ISO points with MUNICIPAL_ONLY vs half-private variants.

**Validations (13 priority rows)**: headers → schema → role → ownership scope → existence → SoD → OCC(412) → state → safety → constraint → temporal → referential → fiscal; two cross-category priority-conflict pairs designed for dual-failure tests.

**Endpoints (57)**: full lifecycle surface plus ops sweep (`POST /programs/{id}/sweep`) and test clock (`POST /_clock/set_current_utc`); every FK has a filtered-list reverse GET.

**Roles (5)**: ProgramAdmin, FieldOperator, UtilitySupervisor, FireDeptLiaison (opaque), PrivateOwnerRep (entity_backed:PrivateOwner with X-User-ID ownership scoping); SoD rules bar verify/review/approve by the same X-User-ID as performer/creator.

**Error catalog**: 56 codes.

**Difficulty design**: 20 instances across all 9 rules (dual-variant ×3, combinatorial modes a/b/c ×3, non-linear SM ×2, depth-3 cascades ×2 from different triggers, priority pairs ×2, boundary precision ×2 on different metrics/endpoints, cross-entity deps ×2, overlap rules with half-open vs cooldown-buffer semantics ×2, compensating invariants ×2). All numeric asserts are pre-computed literals (e.g., Q_20 = 1671 from 80/40/64 psi; flush total 3305 vs forbidden 3304; WO total exactly 25000 at the fee boundary; ISO points 53.3 vs 60.0).

**Corner design**: 59 instances (51 active + 8 `excluded_because` stubs) across all 9 claim-extraction-guide sections — including both OCC stale-version tests, tier-boundary sweeps, terminal lockdowns, RBAC denials, envelope/pagination, and FK reverse-reachability checks. Zero name collisions across the two design files; correct top-level key separation verified.

## Step 3: Copy shared INSTRUCTION.md — 2026-08-13T19:04:32.153Z

Copied `./INSTRUCTION.md` to `tasks/task_1528_hydrant_flow_testing_flushing_program/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T19:11:44.303Z

**Output written:** `/home/ubuntu/github/CodingPRD/tasks/task_1528_hydrant_flow_testing_flushing_program/workspace/PRD.md`

**Document stats:**
- 377 lines, 7,574 words, 55,601 bytes
- 5 top-level sections (§1 Introduction, §2 Global Specifications, §3 Business Logic & Workflows, §4 Endpoint Definitions, §5 Error Code Catalogue)
- 20 subsections: 11 in §2 (2.1 RBAC, 2.2 Response Structure [verbatim], 2.3 Pagination, 2.4 Common Properties, 2.5 Precision, 2.6 OCC, 2.7 Programs, 2.8 Logical Clock, 2.9 Existence, 2.10 Schema, 2.11 Validation Priority), 9 in §3 (Programs/Zones/Inventory, Inspection Cycle, Flow Testing, Flushing, Complaints/Clusters, Outages, Work Orders, ISO Snapshots, Sweep)

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoints[].input + path_params + common fields: 100 required, 100 present, 0 missing
- errors[]: 56 required, 56 present, 0 missing
- state values: 25 required, 25 present, 0 missing
- roles[]: 5 required, 5 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 13 checked, 13 expressed (§2.11 enumerates full priority ordering; individual checks paired with error_ids in §2/§3)
- concurrency_rules[] OCC: 2 checked, 2 expressed (POST /inspections → expected_hydrant_version → ERR_STALE_VERSION 412; POST /work-orders/{id}/approve → expected_work_order_version → ERR_STALE_VERSION 412)
- state_machines[].transitions: all transitions across 9 entities expressed with from/to states, preconditions paired with error_ids, and side effects (incl. cascades on outage create/close, FAIL verify auto-creates work order, complaint auto-cluster, flush complete/abort compensations, ISO supersede)
- calculations[]: 10 checked, 10 expressed (pitot_flow 29.83·d·c²·√p, flow_at_20psi unrounded-pipeline then single round to whole gpm, hydrant_available_fire_flow provisional/approved variants with recorded_at + created_at tiebreak, flush_volume_total round-per-step-then-sum, dechlorination_tablets ceil(mass/8500) with 3.785 L/gal, inspection_due_tier 12/6-month cycles with 30/90-day boundary-pinned tiers, complaint_cluster 3-in-72h with 24h+28h auto-window, part_available_qty reserve/release invariant, work_order_total 5%/10% tiers at 20000/100000 + 1500 fee below 25000 with quoted vs actual variants, iso_rating_points 0.6/0.4 weights with 60-month lookback and 0.5 private weight)
- validations[] conditions: all 13 priority entries matchable to error_ids in prose
- endpoints[].side_effects / applies_to: all expressed in workflow narratives
- entities[].fields[] structured content: defaults (cooldown 60, outlet 2.5, coefficient 0.9, condition_notes "", description "", budget_cap_cents null, expected_return_date null), conditionally-required private_owner_id, initial values, computed vs system vs input provenance all reconstructible
- sibling-branch symmetry: VERIFY/REJECT, APPROVE/REJECT, reschedule-from-REJECTED/MISSED, cancel-from-DRAFT/SUBMITTED/APPROVED, MUNICIPAL_ONLY/ALL_HYDRANTS_HALF_PRIVATE, quoted/actual variants, provisional/approved reads — all rendered with equal density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 576
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Constraint compliance:** I did NOT open, read, grep, or otherwise reference `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`. I did not inspect any sibling task under `/home/ubuntu/github/CodingPRD/tasks/`. Generation was based solely on `skills/prd-bench-doc-generator/SKILL.md`, `skills/prd-bench-doc-generator/section-2.2-response-structure.md` (the verbatim §2.2 contract source), and the task's own `SCAFFOLD.yaml`.

## Step 5: Generate Unit Tests — 2026-08-13T19:41:00.000Z

[RESUME RECOVERY NOTE — orchestrator backfill] The previous pipeline run was killed after Step 5's subagent finished writing artifacts but before its summary was recorded in this worklog; the subagent's verbatim summary is unrecoverable. Post-hoc artifact verification by the resume orchestrator: `test_helpers/` contains all 9 expected files (`__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`); `test_suite/` contains `conftest.py` + 9 test modules (`test_01_platform_envelope` … `test_09_iso_snapshots`). All 18 Python files pass `py_compile` (no truncation). 87 test methods total; every test method carries exactly one `Design: Difficulty/...` or `Design: Corner/...` docstring tag (tag-scan: no file with mismatched test/tag counts). Artifacts judged COMPLETE and reused as-is; Step 5 not re-run.

## Step 6: Generate Implementation — 2026-08-13T19:38:00.000Z

[RESUME RECOVERY NOTE — orchestrator backfill] Same kill window as Step 5: artifacts written, summary never recorded. Post-hoc verification by the resume orchestrator: `workspace/implementation/` contains `app.py` (Flask app factory + blueprint registration, `__main__` binds `0.0.0.0:$PORT`), executable `start.sh` (fg launcher, conditional pip install, `exec python3 app.py`), `requirements.txt` (flask>=3.0,<4.0), and 11 route blueprints under `routes/` (programs, hydrants, inspections, flow_tests, flush_sequences, complaints, outages, work_orders, iso_snapshots, catalog, clock) plus `db.py`/`errors.py`/`middleware.py`/`response.py`/`serializers.py`/`services.py`/`timeutil.py`/`validation.py`. All files pass `py_compile`. Boot probe: `PORT=29876 bash start.sh` boots cleanly and serves requests (envelope-shaped error responses with `meta.api_request_id`/`api_request_timestamp` confirmed; logical clock default 2026-08-01T00:00:00Z confirmed in response meta). No `results.*.json` present → Step 7 never started. Artifacts judged COMPLETE and reused as-is; Step 6 not re-run.

## Step 7: Run tests and iterate — 2026-08-13T20:20:00.000Z

All 8 rounds pass: 87/87 each, 0 failures, 0 errors. The exit criterion is met.

**Summary**

- **Iterations run:** 2 eight-round parallel sweeps (initial diagnostic sweep, then post-fix confirmation sweep), plus 1 solo diagnostic round and manual reproductions against a hand-started server.

- **Tests deleted:** none. The sole failing test (`test_05_flushing.py::TestZoneCooldown::test_sequence_zone_cooldown_buffer_violation`) asserts PRD §3.4's zone-cooldown rule verbatim ("The gap between the new sequence's window and any other `PLANNED` or `IN_PROGRESS` sequence in the same zone must be at least the zone's `cooldown_minutes`; adjacency closer than that buffer — even by a minute — is rejected with `ERR_SEQUENCE_ZONE_COOLDOWN`"), and manual reproduction showed the implementation correctly returns `409 ERR_SEQUENCE_ZONE_COOLDOWN` — the failure was transport-level, not semantic.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:** `test_suite/conftest.py` — added autouse fixture `_drop_stale_keepalive_connections` that calls `api_client.session.close()` before each test. Why: `GenericApiClient` (runner library) holds a module-level `requests.Session` with HTTP keep-alive pooling; under `per-test-server` isolation the server is SIGKILLed and rebooted on the same port before every test, so the pool could hand the first POST of the next test a dead connection. urllib3 retries stale pooled connections for idempotent GETs but not POSTs, surfacing as `RemoteDisconnected`/`ConnectionResetError` — which is what hit this test in all 8 initial rounds under 8-way lockstep CPU load (a solo round passed 87/87). Closing the session empties the pool so every test's first request dials fresh. No assertion was touched.

- **Fixes applied to `implementation/`:** none. The implementation was verified correct by manual reproduction of the exact failing request sequence (program → zone with `cooldown_minutes=60` → 3 hydrants → planned sequence 10:00–11:00 → violating sequence 11:30–12:00 → `409 ERR_SEQUENCE_ZONE_COOLDOWN`).

- **Verification:** final sweep — rounds 1–8 each report `total=87 passed=87 failed=0 errors=0` in `workspace/implementation/results.{1..8}.json`.

## Step 8: Finalize PRD — 2026-08-13T20:26:00.000Z

Step 8 complete. PRD_FINALIZED.md exists at `/home/ubuntu/github/CodingPRD/tasks/task_1528_hydrant_flow_testing_flushing_program/workspace/PRD_FINALIZED.md` and is byte-identical to PRD.md — **zero edits were warranted**.

## Why zero edits

The `<step_7_diff>` contains exactly one fix, and it is a pure fixture bug, not a PRD silence or PRD/impl mismatch:

- **Tests deleted:** none → nothing to pin.
- **test_helpers/ fixes:** none → nothing to pin.
- **test_suite/ fix:** `conftest.py` added the autouse fixture `_drop_stale_keepalive_connections` (verified at `/home/ubuntu/github/CodingPRD/tasks/task_1528_hydrant_flow_testing_flushing_program/test_suite/conftest.py:14-22`). It closes the shared `requests.Session` before each test because per-test-server isolation SIGKILLs/reboots the server on the same port and urllib3 won't retry stale pooled POSTs. This is test-harness transport plumbing; the PRD specifies API behavior and says nothing about HTTP client connection pooling, nor should it. The diff itself states "the failure was transport-level, not semantic." Per the method ("not every item is a PRD silence — some are pure fixture bugs"), no PRD edit traces to it.
- **implementation/ fixes:** none → nothing to pin.

## Verification of the one behavior Step 7 exercised (zone cooldown)

The failing-then-passing test asserts PRD §3.4 verbatim, and I confirmed the PRD already pins the implementation exactly, so no revision was needed:

- PRD §3.4 (`PRD.md:180`): gap to any other `PLANNED`/`IN_PROGRESS` sequence in the same zone must be at least `cooldown_minutes`, closer adjacency → `ERR_SEQUENCE_ZONE_COOLDOWN`; terminal sequences excluded.
- Impl `services.py:375-390` (`zone_cooldown_violation`): same-zone filter, status in `("PLANNED", "IN_PROGRESS")` only, violation iff `gap < timedelta(minutes=zone["cooldown_minutes"])`. Sole callsite `routes/flush_sequences.py:78-83` raises `ERR_SEQUENCE_ZONE_COOLDOWN` with HTTP 409.
- Supporting pins also match: `cooldown_minutes` default 60 (`PRD.md:142` ↔ `routes/catalog.py:34` `default=60`); error table `PRD.md:373` lists `ERR_SEQUENCE_ZONE_COOLDOWN | 409` ↔ impl raises 409.
- All 8 final-sweep result files confirm `total=87 passed=87 failed=0 errors=0`.

## Required summary

- **Line counts / %-delta:** PRD.md = 377 lines; PRD_FINALIZED.md = 377 lines; delta = 0 (0.0%). Byte-identical (`cmp` clean).
- **Changes:** none.
- **Per-edit pre-edit search log:** no edits were committed, so no per-edit log entries exist. The global due-diligence search performed in lieu of edits: subject = zone-cooldown rule (the only Step 7 behavioral site); paths enumerated and read = `implementation/services.py:365-390`, `implementation/routes/flush_sequences.py:1-100`, `implementation/routes/catalog.py:34-38`, `implementation/serializers.py:30`, `implementation/errors.py:70`, plus PRD.md lines 132, 142, 176-200, 373. Conclusion: PRD §3.4 wording already uniquely determines the single impl callsite and all cooldown-touching paths; any edit would have risked violating the no-new-mismatch rule with zero compensating benefit.

## Step 9: Complete PRD — 2026-08-13T20:42:00.000Z

Step 9 complete. `/home/ubuntu/github/CodingPRD/tasks/task_1528_hydrant_flow_testing_flushing_program/workspace/PRD_COMPLETED.md` produced as a minimal patch over PRD_FINALIZED.md.

**Size**: PRD_FINALIZED.md 377 lines / 55,601 chars → PRD_COMPLETED.md 377 lines / 59,143 chars (char-delta +3,542; all edits in-place, no lines added or removed).

**Counts**: 22 ambiguity-pins, 2 mismatch-revisions, 1 internal cross-reference correction (not impl-related).

**Changes** (one bullet each):

- §2.1 — insert — ambiguity — whitespace-only `X-User-ID`/`X-User-Role` headers treated as empty — implementation/middleware.py:23
- §2.2 — insert — ambiguity — `api_request_timestamp` rendered from the logical clock on success and error envelopes — implementation/response.py:12-16
- §2.3 — revise — ambiguity — `limit`/`offset` out-of-range values are clamped (limit→[1,100], offset→≥0); non-integer values rejected with `ERR_INVALID_REQUEST` — implementation/validation.py:160-171
- §2.3 — revise — ambiguity — `has_more` true exactly when offset + returned < total_count; `created_at` ties broken by creation order — implementation/validation.py:174-186
- §2.4 — insert — ambiguity — `version` starts at 1 on creation — implementation/db.py:43-52
- §2.7 — revise — ambiguity — outage tagging pinned as the *only* operation gated on program `OPEN`; closing an already-`CLOSED` program rejected with `ERR_PROGRAM_NOT_OPEN` — implementation/routes/programs.py:69-72, implementation/routes/outages.py:53-57
- §2.7 — revise — cross-reference — fixed stale pointer "hard gate on ISO publication (§3.7)" → (§3.8) — n/a (PRD internal defect)
- §2.8 — revise — ambiguity — clock accepts any valid instant (no monotonicity requirement); `current_utc` echoes the submitted `to_iso8601` string verbatim — implementation/routes/clock.py:12-28
- §2.10 — revise — ambiguity — body must be a JSON object (non-object/unparseable rejected); no-body endpoints reject any non-empty JSON object as unknown-field — implementation/validation.py:111-120, 153-157
- §2.10 + §2.11 items 2/3 — revise — mismatch — the conditional-required `private_owner_id` rule is evaluated immediately *after* role membership, not at the schema layer — implementation/routes/hydrants.py:45-50
- §2.11 items 4/5 — revise — mismatch — swapped order: resource existence (now 4) precedes ownership scope on inspection record (now 5), since the ownership check needs the persisted inspection — implementation/routes/inspections.py:99-116
- §3.2 — revise — ambiguity — resubmission overwrites `condition_notes` too; omitted `condition_notes` resets to empty — implementation/routes/inspections.py:123-126
- §3.2 — revise — ambiguity — on VERIFY the hydrant's version increments once for the baseline update and once more when the tier recomputation changes the tier — implementation/routes/inspections.py:156-159, implementation/services.py:75-81
- §3.3 — insert — ambiguity — flow-test list endpoint filters: `hydrant_id`, `status` — implementation/routes/flow_tests.py:89-100
- §3.3 — revise — ambiguity — result-submission window bounds are inclusive: submission at exactly `window_start` or `window_end` is accepted — implementation/routes/flow_tests.py:122-134
- §3.3 — revise — ambiguity — provisional recompute tiebreak extended: after `created_at` ascending, remaining ties broken by creation order — implementation/services.py:124
- §3.3 — revise — ambiguity — reschedule retains prior readings, computed flows, and classification until new results are submitted — implementation/routes/flow_tests.py:218-221
- §3.4 — revise — ambiguity — at creation every step must be `PENDING` and carry only declared step fields (else `ERR_INVALID_REQUEST`); empty steps list accepted; steps stored/returned in ascending `step_index` order — implementation/validation.py:35-73
- §3.4 — insert — ambiguity — flush-sequence list endpoint filters: `program_id`, `zone_id`, `hydrant_id`, `status` — implementation/routes/flush_sequences.py:103-112
- §3.5 — revise — ambiguity — `RESOLVED` close on an already-terminal complaint rejected with `ERR_COMPLAINT_NOT_CLOSABLE` (distinct from the premature-close error) — implementation/routes/complaints.py:108-125
- §3.6 — insert — ambiguity — outage list endpoint filters: `hydrant_id`, `status` — implementation/routes/outages.py:87-98
- §3.7 — insert — ambiguity — work-order list endpoint filters: `hydrant_id`, `source_inspection_id`, `status` — implementation/routes/work_orders.py:70-79
- §3.7 — revise — ambiguity — negative `on_hand_qty` on part create rejected with `ERR_INVALID_REQUEST`; restock `add_qty` must be > 0 (else `ERR_INVALID_REQUEST`) — implementation/routes/catalog.py:66-67, 104-105
- §3.8 — insert — ambiguity — ISO snapshot list endpoint filters: `program_id`, `status` — implementation/routes/iso_snapshots.py:55-66
- §3.8 — revise — ambiguity — inspection-currency window bounds are inclusive, matching the flow-currency rule — implementation/services.py:296-301
- §3.8 — revise — ambiguity — zero total weight (e.g. `MUNICIPAL_ONLY` over an all-private program) publishes both coverages as 0 and `iso_points` as 0.0 — implementation/services.py:305-311
- §3.9 — revise — ambiguity — escalation applied at most once per outage (already-escalated outages not re-modified) — implementation/routes/programs.py:102-113
- §3.9 — revise — ambiguity — sweep count semantics pinned: `missed_flow_tests`/`escalated_outages` count this run's transitions; `tier_recomputed_hydrants` counts every program hydrant evaluated (including `DECOMMISSIONED` and unchanged); hydrant version increments only on actual tier change — implementation/routes/programs.py:84-119

Everything else in the implementation (all 41 endpoints, state machines, the pitot/Q20/classification pipeline, flush-volume and dechlorination math, tiered pricing, ISO weighting, the complaint-cluster rule, outage cascades, OCC scope, error catalogue IDs/statuses, and the §2.11 temporal-before-pressure example) was already pinned uniquely by the PRD and required no change.
