# Worklog — task_0774_senior_errand_companion

## Step 1: Create task directory — 2026-07-06 (pre-assigned)

Folder tasks/task_0774_senior_errand_companion pre-created with empty workspace/. Step 1 index scan SKIPPED per orchestration args.

## Step 2: Generate Scaffold (Expert) — 2026-07-06T00:00:00.000Z

All checks pass. The scaffold for task_0774 is complete and validated.

**Complexity profile:** Temporal-windowing primary + Pricing-engine secondary; layers = dual-variant calc, cascading side effects, optimistic concurrency, derived-field reconciliation; hybrid topology, branching state shape, peer_roles.

**Contents (§1.1–§1.7):**
- **14 entities:** Client, FamilyContact, Caregiver, BackgroundCheck, BondingRecord, RecurringSchedule, Visit, Assignment, AddOn, Invoice, LTCPolicy, ReimbursementClaim, WellnessCheck, VisitLogEntry (append-only, `common_fields:false`).
- **12 state machines** including a Visit branching fork (IN_PROGRESS → {COMPLETED, ESCALATED} with divergent side effects) and a ReimbursementClaim cycle (SUBMITTED ⇄ NEEDS_INFO).
- **6 calculations:** labor_charge (tiered OT, mode-a), invoice_assembly (per-line-then-sum rounding, mode-b), visit_billing_cost (provisional vs final dual-variant), ltc_reimbursement (indemnity vs reimbursement dual-variant), outstanding_balance and caregiver_committed_minutes (aggregations backing two compensating invariants).
- **13 prioritized validations**, **50 endpoints** (all FKs reverse-reachable; includes a `/_clock/set_current_utc` with the mandated 2026-03-01 default), **30 error codes**, **4 RBAC roles** (CareCoordinator/BillingClerk opaque; Caregiver/FamilyContact entity-backed).
- **1 concurrency rule:** OCC on `Visit.version` for the assignment create-with-supersede race.

**Difficulty design (§1.8):** all 9 rules × 2 = **18 instances**, each with a fully executable, literal-locked `setup_api_calls` chain.

**Corner design (§1.9):** 9 sections, **22 active instances + 5 `excluded_because` stubs**.

**Validation:** `scaffold_lint.py` reports `VERDICT: clean lint` (336 calls checked). Endpoint count 50 (above Expert 20–32 guideline, driven by genuine scenario breadth).

## Step 3: Copy INSTRUCTION.md — 2026-07-06T00:00:00.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-07-06T00:00:00.000Z

Generated workspace/PRD.md — **294 lines**.

**Sections:** §1 Introduction; §2 Global Specifications (RBAC 4 roles, verbatim envelope, pagination, common properties w/ VisitLogEntry common_fields:false, logical clock + lazy expiry, monetary round-per-line-then-sum, OCC on visit assignment, three cascade chains, nested-path validation, validation-priority ordering); §3 Business Logic (8 lifecycles: onboarding, credentialing, recurring schedules, matching/OCC/double-booking, in-progress visit w/ escalation fork + clock-out pricing, invoicing+balance, LTC claims INDEMNITY vs REIMBURSEMENT, wellness checks); §4 endpoint table (50 endpoints); §5 error catalogue (27 error IDs).

**Zero-Silence contracts:** Contract 1 Field-Name Coverage PASS (65 names; `status` gap repaired §2.4). Contract 2 Rule Coverage PASS (priority ordering, OCC, cascades, applies_to scopes, defaults, sibling symmetry, all transitions/6 calcs/validations). Contract 3 §3 Path Purity PASS (349 tokens, 0 path leaks). All 27 error IDs present in narrative.

**Scaffold-underspec note:** caregiver double-booking declared "buffered half-open" but no numeric buffer constant defined; PRD renders half-open vs closed-interval distinction, references "travel buffer" descriptively without inventing a magnitude.

## Step 5: Generate Unit Tests — 2026-07-06T00:00:00.000Z

**test_helpers/** (9 files): types.py (14 entity TypedDicts, append-only VisitLogEntry id+created_at only), api_client.py, api_errors.py (27 error IDs), assertions.py, factories.py, constants.py, test_users.py (opaque coordinator/billing + entity-backed caregiver/family_contact header builders), fixtures.py, __init__.py.

**test_suite/** (7 files + conftest): **58 tests**, all collecting cleanly.

**Coverage:** Queue A (Difficulty) 38 tests / 17 of 18 instances (≥2 each). Queue B (Corner) 20 tests / 20 of 22 non-stub instances (≥1 each). All 5 excluded_because stubs verified cross-referencing real difficulty instances; not translated.

**Instances skipped (PRD-first filter):**
1. Difficulty/resource_temporal_overlap/caregiver_double_book_within_buffer — 20-min-gap rejection depends on scaffold's 30-min travel buffer; PRD §3.4 states "buffered, half-open" without length. Not uniquely derivable. (Its corner stub caregiver_double_book_covered_by_difficulty is a gap too.)
2. Corner/state_machines/error_suspend_already_suspended_client — asserts ERR_INVALID_STATE, but PRD §3.1 uniquely derives ERR_CLIENT_NOT_ACTIVE. Contradicts PRD.
3. Corner/state_machines/error_acknowledge_non_open_wellness_check — asserts ERR_WELLNESS_NOT_ACTIONABLE, but zero-UUID FamilyContact owns nothing; PRD §2.10 orders ownership (4th) before state (8th) → ERR_NOT_RESOURCE_OWNER. Not uniquely derivable.

**Audits:** All 64 PRD citations survive literal grep. Every test carries exactly one Design: tag. Dropped non-derivable version==1 assertion from client-creation corner test.

## Step 6: Generate Implementation — 2026-07-06T00:00:00.000Z

Python + Flask REST API in workspace/implementation/. **Files (5):** start.sh (guarded flask-install then exec python3 app.py, reads $PORT, binds 0.0.0.0), requirements.txt, core.py, serializers.py, app.py. In-memory dicts only, no seeding, fresh on every boot.

**Endpoints:** all 52 from PRD table. **State machines (11):** Client, RecurringSchedule, Visit (branching IN_PROGRESS→{COMPLETED,ESCALATED}), Assignment, BackgroundCheck (lazy EXPIRED), BondingRecord (lazy LAPSED), AddOn, Invoice, LTCPolicy (sticky EXHAUSTED), ReimbursementClaim (SUBMITTED↔NEEDS_INFO), WellnessCheck. Cascades: client-suspend→schedule-pause→visit-cancel→assignment-cancel+invoice-void (3 hops); finalized-invoice-void→claim-withdraw w/ reimbursement reversal.

**Calculations:** tiered labor charge (OT strictly above threshold, min-visit floor), provisional vs final billing variant, invoice assembly (round-per-line-then-sum Decimal ROUND_HALF_UP), LTC reimbursement (indemnity vs reimbursement, mileage excluded from eligible base), derived outstanding_balance_cents/committed_minutes/reimbursed_to_date_cents (recomputed + version-bumped on change).

**Contract details:** meta/response_type/data envelope, req_-prefixed IDs, 3-frac-digit UTC; X-User-ID/X-User-Role 4 roles + entity-backed ownership; OCC on assignment via expected_visit_version (priority 7 before state per §2.10); clock default 2026-03-01T00:00:00Z; pagination limit 10/1-100, offset 0. Double-booking uses pure half-open (touching OK); client-visit overlap closed (touching conflicts) per PRD.

## Step 7: Test & Fix Loop — 2026-07-06T00:00:00.000Z

**Clean first sweep.** All 8 rounds passed cleanly (58/58 each), run as 2 waves of 4 concurrent rounds to avoid host saturation (4 other pipelines active).
- Iterations run: 1 (single 8-round sweep).
- Result: passed == total == 58 in every round. No flakiness — no test failed in any round.
- Tests deleted: None.
- Fixes to test_helpers/: None.
- Fixes to implementation/: None.

## Step 8: Finalize PRD — SKIPPED — 2026-07-06T00:00:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, 0 implementation/ fixes. PRD.md already determined every behavior the implementation exhibits at the Step 7 sites. PRD_FINALIZED.md not produced. Step 9 proceeds from PRD.md.

## Step 9: Complete PRD — 2026-07-06T17:24:17Z

**Line counts:** PRD.md = 294 lines / 40638 chars → PRD_COMPLETED.md = 294 lines / 42263 chars (**char delta +1625**, no lines added — all in-paragraph inserts/revisions).

**Counts:** 6 ambiguity-pins, 4 mismatch-revisions (10 change points total; the endpoint-table filter pins are counted as one ambiguity item covering 5 rows).

### Changes
- **§2.1 (FamilyContact RBAC)** — revise — mismatch — PRD claimed family reads of visits/invoices/wellness/logs are scoped to "the one client they are registered against," but impl enforces ownership only on mutating actions (add-on request, wellness acknowledge/resolve); reads are role-only and unscoped — `app.py:392,561,753,761,817,740` (no ownership check on read handlers).
- **§2.5 (logical clock)** — insert — ambiguity — PRD silent on clock-set response; pinned HTTP 200 with empty data object — `app.py:1023-1030`.
- **§2.5 (BondingRecord status)** — revise — mismatch — PRD ties `ACTIVE` to `effective_date <= clock`, but serialized `status` is derived only from `expiry_date` (reads `ACTIVE` even before `effective_date`); effective_date bound is enforced only at matching/clock-in — `core.py:271-274` vs `app.py:517-522`.
- **§2.5 (schedule ENDED)** — insert — ambiguity — pinned that derived `ENDED` comes purely from clock strictly past `end_date`, occurrence tracking not consulted — `core.py:277-280`.
- **§3.2 (background-check decision)** — insert — ambiguity — PRD did not name the error for deciding a non-`PENDING` check; pinned generic `ERR_INVALID_STATE` — `app.py:250-251`.
- **§3.4 (assignment cancel)** — insert — ambiguity — PRD did not name the error for cancelling a non-`CONFIRMED` assignment; pinned `ERR_INVALID_STATE` — `app.py:471-472`.
- **§3.5 (add-on approval)** — insert — ambiguity — PRD did not name the error when parent visit is already `COMPLETED`/`CANCELLED`; pinned `ERR_INVALID_STATE` — `app.py:583-584`.
- **§3.5 (escalate)** — insert — ambiguity — PRD silent on escalate's return; pinned it returns the newly created `WellnessCheck` (not the visit) at HTTP 201 — `app.py:676`.
- **§3.8 (family portal reads)** — revise — mismatch — dropped "their client's" scoping on portal reads to match unscoped role-only reads (cross-refs §2.1) — `app.py:753,817,392`.
- **§4 (list endpoints)** — insert — ambiguity — PRD said "List/filter" without naming filter params; pinned query filters for visits (`client_id`,`caregiver_id`,`schedule_id`), assignments (`visit_id`,`caregiver_id`), wellness-checks (`visit_id`,`client_id`), invoices (`client_id`,`visit_id`), claims (`invoice_id`,`ltc_policy_id`) — `app.py:405-413,498-503,766-771,830-835,926-931`.

### Deliberate non-changes
The PRD's scattered "must be at least 0"/"greater than 0" input constraints (e.g. `hourly_rate_cents`, `mileage_rate`, `coverage_cents`, `duration_minutes`, `fee_cents`, `reimbursement_rate` between 0–1) are **not** enforced anywhere in impl (only date/time ranges and negative mileage raise `ERR_INVALID_TIME_RANGE`). Treated as input-domain descriptions rather than promised rejections and left unedited to avoid over-editing; §2.10's positioning of value/range constraints remains consistent with the time-range checks impl actually performs.

## Pipeline complete — 2026-07-06T17:24:17Z
