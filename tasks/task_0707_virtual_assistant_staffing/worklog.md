# Worklog — task_0707_virtual_assistant_staffing

## Step 1: Create task directory — 2026-06-29T10:11:05.644Z

Task directory `tasks/task_0707_virtual_assistant_staffing` was pre-created (Step 1 index scan skipped per orchestrator instruction to avoid parallel-run ID contention). Created `workspace/` subdirectory. Verified `INSTRUCTION.md` exists at project root and all `skills/prd-bench-*` are present. Difficulty: Expert (passed only to Step 2 scaffold-generator).

## Step 2: Generate Scaffold (finish — two missing design files only) — 2026-06-29T10:38:00.000Z

Resumed Step 2. SCAFFOLD.yaml was already complete & valid (§1.1–§1.7, no design keys) and was left untouched. Spawned one blocking subagent (read prd-bench-scaffold-generator SKILL.md + existing SCAFFOLD.yaml) to generate ONLY the two missing design-index files at EXPERT tier, cross-referenced to SCAFFOLD.yaml:
- SCAFFOLD_DIFFICULTY_DESIGN.yaml — single top-level key `scaffold_difficulty_design` (§1.8 depth index); ~36 named instances. 76710 bytes.
- SCAFFOLD_CORNER_DESIGN.yaml — single top-level key `scaffold_corner_design` (§1.9 breadth index); ~78 named instances. 101859 bytes.
Verified: both parse as valid YAML with the correct single top-level key; SCAFFOLD.yaml unchanged (still has no design keys). All three scaffold artifacts now present.

## Step 3: Copy shared files — 2026-06-29T10:38:30.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md (build contract). Idempotent.

### Step 2 — subagent verbatim summary (authoritative counts; supersedes my on-disk estimate above)

Generated the two missing Step-2 design-index files at EXPERT depth/breadth, both cross-referenced to the existing SCAFFOLD.yaml.

SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8 depth probe) — single top-level key scaffold_difficulty_design; 18 instances = all 9 Difficulty Rules × 2: dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant — 2 each. Each instance's two members satisfy §0.5's differentiation clause. All numeric asserts are computed literals (invoice 66000, surcharge invoice 27000, billable 0.25/0.5h, rollover carry 5h, match_score 0.94, SLA strict-> boundary timestamps).

SCAFFOLD_CORNER_DESIGN.yaml (§1.9 breadth probe) — single top-level key scaffold_corner_design; 44 instances across 8 sections: entities (10), state_machines (9), calculations (2), validations (11), endpoints (3), rbac (2), cross_cutting_complexity_layers (6), consistency_model (1). 42 full test recipes; 2 excluded_because: stubs citing real §1.8 instance names (no test_recipe).

Verification: both files valid YAML with exactly their one required top-level key; all 62 instance names unique across §1.8 ∪ §1.9; every excluded_because.difficulty_instance resolves to a real §1.8 name; scaffold_lint.py tasks/task_0707_virtual_assistant_staffing → VERDICT: clean lint (600 calls scanned, 0 violations); SCAFFOLD.yaml not modified (untracked task dir, empty diff). Note: Rule 8 resource_temporal_overlap grounded in SLA response-window vs resolution-window interval semantics.

## Step 4: Generate PRD — 2026-06-29T10:42:00.000Z

Generated workspace/PRD.md — a 251-line PRD for the va-staffing EXPERT-band domain (13 entities, 6 state machines, 7 calculations, 22 validations, 45 endpoints, 22 errors, 3 roles). Design files (§1.8/§1.9) withheld.

Structure: §1 Introduction (constituencies, coupling complexity, logical-clock determinism). §2 Global Specs — 10 subsections: 2.1 RBAC, 2.2 fixed response envelope (verbatim), 2.3 Pagination, 2.4 Identity/Timestamps/Versioning, 2.5 Logical Clock, 2.6 Nested Reference Resolution, 2.7 Validation Ordering, 2.8 Monetary/Hour Precision, 2.9 OCC on Cycle Close, 2.10 State-Driven Cascades. §3 Business Logic — 8 subsections (config → client intake/suspension → matching/onboarding → task queue/SLA → time logging/approval/pricing → add-ons → escalation/replacement → cycle close/rollover/invoicing). §4 45-endpoint table. §5 22-error table.

Hard Contracts — all PASS (verified mechanically): Contract 1 Field-Name Coverage 81/81 (fixed 2 omissions email/full_name in §3.3). Contract 2 Rule Coverage — all 22 error IDs in narrative; all state/enum values as exact backticked strings; all 7 calc formulas as precise prose (round-per-tier-then-sum, ceil-to-15-min grid, weighted match score created_at ASC tie-break, strict > SLA boundary, dual PROVISIONAL/FINAL & CAP_BINDING/CAP_SLACK variants, SLA breach credit); OCC rule with expected_cycle_version + ERR_STALE_CYCLE_VERSION/412. Contract 3 §3 Path Purity 333 tokens, 0 violations.

Notable scattering: endpoint params split across subsections (expected_cycle_version in §2.9 vs close workflow §3.8; ERR_ADDON_REQUIRED gate spans §3.4/§3.6); constants embedded (15-min/0.25h grid, 40.0h/week cap, 0.5/0.3/0.2 weights); 3-hop replacement & 3-hop client-close cascades enumerated; immutable SkillTag/SlaPolicy/Clock carry only id/created_at.

## Step 5: Generate Unit Tests — 2026-06-29T10:58:00.000Z

Generated complete test infrastructure from the two design indices (design-index-only contract honored).

test_helpers/ (9 files): types.py (status enums + entity TypedDicts; immutable SkillTag/SlaPolicy/Clock omit updated_at/version), api_client.py (ApiClient, one method per endpoint, all 45 under /va-staffing), api_errors.py (22-entry ApiErrorId enum + HTTP-status map), assertions.py (per-entity + cycle/invoice arithmetic invariants), factories.py (input-field-only payloads, unique-email helper), constants.py (grid/weight/clock constants), test_users.py (opaque StaffingManager constant + per-instance make_client_headers/make_va_headers entity-backed identity), fixtures.py (setup_active_client_engagement, setup_active_client_with_active_addon, task-lifecycle/time-entry/cycle helpers), __init__.py.

test_suite/ (conftest + 7 files), 72 tests total: test_01 intake/config (16), test_02 engagement matching (6), test_03 task queue/SLA (14), test_04 time tracking/billing (15), test_05 cycle rollover (6), test_06 cascades/escalation (10), test_07 validation precedence/OCC (5).

Coverage: Difficulty (queue A) 16/18 instances translated (each ≥2 tests), 2 skipped. Corner (queue B) 39/41 non-stub instances translated (each ≥1 test), 2 skipped; both excluded_because: stubs correctly not translated.

Design-filter skips (4, gaps left as gaps): approve_no_open_cycle_beats_stale_version_pairing (Diff) and time_entry_approve_requires_open_retainer_cycle (Diff 7.B) — "client's only cycle CLOSED while client ACTIVE" unreachable (PRD §3.8 mints successor OPEN cycle on every close), ERR_NO_OPEN_CYCLE not uniquely-derivable; time_entry_create_no_open_cycle_returns_cycle_not_open (Corner) — same root cause; replace_with_benched_va_returns_replacement_ineligible (Corner) — recipe passes never-created UUID as va_id, PRD §2.7 body-FK check (priority 4, ERR_REFERENCED_ENTITY_NOT_FOUND) precedes priority-21 eligibility gate so asserted ERR_REPLACEMENT_INELIGIBLE fails two-reader test.

Validation: all 72 tests collect; all modules byte-compile; every docstring PRD citation is a verbatim substring of PRD.md; every docstring ends with exactly one Design: Difficulty/... or Design: Corner/... line resolving to a real instance; no skip/skipif/xfail; no scaffold/Table/§ leakage. Tests not executed against a live server (no impl in scope for this step).

## Step 6: Generate Implementation — 2026-06-29T10:58:30.000Z

Built complete Python + Flask in-memory REST API at workspace/implementation/ (23 source files, ~2400 LOC).

start.sh — foreground launcher (executable); guards pip install on cheap import flask check, then exec python3 app.py. requirements.txt — flask>=3.0,<4.0 only. app.py — Flask entry, error handlers, fetch-or-404 + FK-existence helpers, generic list responder, route registration, app.run(host=0.0.0.0, port=int(os.environ.get(PORT,10000))).
Foundation: errors.py (22-code catalog + ApiError), response.py (envelopes), clock.py (logical clock default 2026-03-01T00:00:00Z, 3-fractional-digit ISO8601), db.py (in-memory store + system-field stamping), middleware.py (auth/RBAC), pagination.py, validation.py, ownership.py (transitive client/VA ownership), serialize.py (computed fields at read time), sla.py (SLA due/state), calculations.py (Decimal/ROUND_HALF_UP money + hours).
Route groups: routes_config (clock, skill-tags, sla-policies, virtual-assistants), routes_clients, routes_engagements (+addons), routes_tasks, routes_time, routes_cycles, routes_escalations, routes_invoices. All 53 endpoints implemented.

In-memory dicts keyed by id; NO seeding at startup; no SQLite/disk/tmp persistence (grep-verified); state wiped on restart. start.sh reads $PORT (default 10000), binds 0.0.0.0, foreground via exec; verified bash start.sh boots and answers HTTP 200 <1s.

Live end-to-end verification: match-score 0.94 exact; cycle balances; 16min→0.5h ceil-to-15min billing; OCC stale-version 412; rollover cap (unused 9.5 capped to 5.0); FINAL/PROVISIONAL invoice pricing; SLA breach strict > boundary (00:30==due ON_TRACK; 00:30:01 RESPONSE_BREACHED; RESOLUTION_BREACHED dominates/latches on DONE); SLA breach credit; overage tier; specialized add-on gate + surcharge; suspend/resume revert (QUEUED↔ASSIGNED); 3-hop replacement cascade; validation ordering (403 before 404, pagination 422). Envelope/meta match §2.2.

Open-choice decisions: created_at/updated_at use logical-clock value (§2.5); hidden monotonic _seq (stripped from output) gives deterministic earlier-registered total order for list sort (§2.3) and VA match created_at ASC tie-break (§3.3) — id never consulted. api_request_timestamp uses real wall-clock. Computed fields derived at read time; transitions still bump version/updated_at on touched entities (§2.10). Replacement VA keeps prior availability status (PRD §3.7 only increments active_engagement_count; status→ENGAGED tied to engagement accept §3.3).

## Step 7: Run Tests and Iterate — 2026-06-29T11:14:00.000Z

Iterations run: 3 sweeps (baseline 65/72, then 70/72, then 72/72).

Tests deleted: None. All 72 tests retained; failures were a PRD/impl mismatch and two test-setup bugs, not PRD-silence or non-unique-derivability.

Fixes applied to implementation/ (STEP 3 — PRD/impl mismatch on timestamp format): The implementation formatted EVERY timestamp with three fractional digits, but PRD §2.4 pins three fractional digits only for audit timestamps api_request_timestamp/created_at/updated_at, while PRD §2.5's only worked examples for the logical clock (current_utc) and all clock-derived lifecycle *_iso stamps are second-precision (2026-03-01T00:00:00Z, lines 80 & 170). Split the formatter so clock-derived values match the PRD's canonical second-precision form:
- clock.py — added _fmt_clock (second-precision) and LogicalClock.iso_clock(); changed module-level iso(dt) helper (used by sla.compute_due for response_due_iso/resolution_due_iso) to second-precision. _fmt/LogicalClock.iso() (three fractional digits) retained for created_at/updated_at.
- db.py — added clock_iso_logical() (second-precision); clock_iso() (three digits) kept for created_at/updated_at.
- serialize.py — current_utc now uses clock.iso_clock().
- Routed all 10 lifecycle *_iso stamp sites (assigned_at_iso, first_action_at_iso, completed_at_iso, approved_at_iso, opened_at_iso, closed_at_iso in routes_tasks.py, routes_time.py, routes_cycles.py, routes_clients.py, services.py) to clock_iso_logical(). Verified live: current_utc → ...00Z, created_at/api_request_timestamp → ....000Z.

Fixes applied to test_suite/ (STEP 2 — setup inconsistent with PRD precedence/priority-order):
- test_07_validation_precedence_occ.py — test_task_assign_blocked_by_non_active_client and test_task_assign_on_suspended_client_leaves_task_queued: reordered setup to suspend the client BEFORE creating the task. PRD §3.2 moves a client's existing QUEUED/ASSIGNED tasks to BLOCKED on suspension, and PRD §2.7 ranks the state gate (priority 8, ERR_INVALID_STATE) ahead of the client-active gate (priority 9, ERR_CLIENT_NOT_ACTIVE); the original create-then-suspend ordering left the task BLOCKED, so a faithful impl returns ERR_INVALID_STATE. Creating the task after suspension keeps it QUEUED, so the priority-9 ERR_CLIENT_NOT_ACTIVE gate (the rule under test) is reached.
- test_03_task_queue_sla.py — test_sla_resolution_boundary_strict_greater_than and test_sla_resolution_due_iso_is_assigned_plus_resolution_hours: changed setup from create_assigned_task to create_in_progress_task so first_action_at_iso is stamped within the response window. PRD §3.4's priority-ordered SLA eval would otherwise return RESPONSE_BREACHED (open response window past response_due, first_action null), masking the resolution boundary these tests isolate. (Surfaced only after the timestamp fix made their *_iso equality assertions pass.) Mirrors the existing passing test_sla_response_window_cleared_once_first_action_taken convention.

Fixes applied to test_helpers/: None — helpers were generic and PRD-faithful; bugs were in per-test setup ordering.

Final sweep result: 72/72 × 8 rounds, 0 failed, 0 errors, fully deterministic across all rounds. No tests deleted, no assertions weakened, no skip/xfail added, no endpoints/fields/seeding added to implementation.

## Step 8: Finalize PRD — 2026-06-29T11:16:30.000Z

Produced workspace/PRD_FINALIZED.md. Line counts: PRD.md = 251, PRD_FINALIZED.md = 253, delta +2 (+0.80%). One new paragraph inserted into §2.5; no existing prose altered.

Change: §2.5 (The Logical Clock) — insert — pinned the rendering format of clock-derived values: current_utc, SLA due dates (response_due_iso/resolution_due_iso), and all six lifecycle *_iso stamps (assigned_at_iso, first_action_at_iso, completed_at_iso, approved_at_iso, opened_at_iso, closed_at_iso) are second-precision ISO 8601 UTC (no fractional digits, e.g. 2026-03-01T00:00:00Z), explicitly distinct from the three-fractional-digit audit stamps created_at/updated_at/api_request_timestamp. (impl: clock.py _fmt_clock/iso_clock/iso, db.py clock_iso_logical, serialize.py current_utc).

Why only one edit: STEP 3 timestamp format was genuine PRD silence (§2.5 was silent on current_utc/*_iso/SLA-due formats while §2.2/§2.4 pin three fractional digits only for audit stamps) → edited. STEP 2 test_07/test_03 setup reorderings were pure fixture bugs respecting behavior PRD already determines (§3.2 suspension→BLOCKED, §2.7 state gate priority 8 before client-active priority 9, §3.4 priority-ordered SLA eval) → no PRD edit.

Pre-edit search log (Edit 1, §2.5): (a) subject = ISO-8601 rendering precision of logical-clock value + every clock-derived stamp vs audit stamps. (b) enumerated impl paths: current_utc (serialize.py:51 → db.clock.iso_clock); all *_iso writes via db.clock_iso_logical (routes_tasks/time/cycles/clients, services); SLA due via sla.compute_due → clock.iso; audit stamps via db.clock_iso → _fmt and api_request_timestamp via now_iso_real → _fmt. (c) wording adjustment: phrased current_utc as "sub-second component dropped on read-back" (set endpoint accepts sub-second but render truncates), enumerated six *_iso + two due-date fields by name, explicitly excluded created_at/updated_at/api_request_timestamp so §2.2/§2.4 three-digit prose is not contradicted.

## Step 9: Complete PRD — 2026-06-29T11:18:00.000Z

Produced workspace/PRD_COMPLETED.md via full PRD-vs-implementation scan. PRD_FINALIZED.md: 253 lines, 42166 chars → PRD_COMPLETED.md: 253 lines, 44212 chars. Char delta +2046; line count unchanged (all edits in-paragraph, zero new paragraphs/sections). 9 changes: 8 ambiguity-pins, 1 mismatch-revision.

Changes:
- §2.1 Authentication — revise — mismatch — PRD said "every request must carry two headers"; impl only authenticates X-User-Role and never rejects a missing X-User-ID (StaffingManager with no X-User-ID succeeds; Client/VA only fail later as ERR_FORBIDDEN on ownership). (middleware.py:18-22, ownership.py:62-70)
- §2.2 api_request_id — insert — ambiguity — pinned exact shape: req_ + 20 random ASCII-alphanumeric chars. (response.py:9-11)
- §2.2 api_request_timestamp — insert — ambiguity — pinned it is read from host real wall-clock, not the logical clock. (response.py:18, clock.py:36-38)
- §2.3 Pagination — insert — ambiguity — pinned non-integer limit/offset also yields ERR_PAGINATION_INVALID (PRD only covered out-of-range). (pagination.py:17-21)
- §2.3 List ordering — insert — ambiguity — pinned created_at-tie tie-break: ties broken by internal insertion order (earlier-persisted first), since logical-clock created_at can repeat. (pagination.py:39, db.py:60)
- §2.4 created_at/updated_at — insert — ambiguity — pinned both stamped from logical clock (three-fractional-digit), not wall-clock. (db.py:37,53,68)
- §2.5 Clock resource — insert — ambiguity — pinned singleton Clock id is literal string "clock" (not UUID) and its created_at tracks live logical-clock value. (serialize.py:47-52)
- §3.3 Engagement match_score — insert — ambiguity — pinned match_score is null when va_id supplied explicitly (number only for auto-matched proposals). (routes_engagements.py:36,58-64)
- §3.3 Engagement activate — insert — ambiguity — pinned onboarding_checklist_done required (ERR_INVALID_REQUEST if absent) and present-but-false yields ERR_INVALID_STATE. (routes_engagements.py:147-154)
- §3.7 Escalation open — insert — ambiguity — pinned opening an escalation not gated on an active engagement: with null active_engagement_id the escalation is still created OPEN with null engagement_id. (routes_escalations.py:38-44)

Remaining PRD prose (validation ordering, SLA eval, cycle/invoice arithmetic, cascades, RBAC table, error catalogue) already uniquely pinned and matching impl; no further edits warranted.

## Pipeline complete — 2026-06-29T11:18:30.000Z

EXIT CONDITION MET: workspace/PRD_COMPLETED.md exists. All steps 2–9 done. Final Step 7 sweep: 72/72 × 8 rounds deterministic.
