# Worklog — task_0519_home_infusion_therapy

## Step 1: Create task directory — 2026-06-30T15:03:51.000Z

Created `tasks/task_0519_home_infusion_therapy/` and `tasks/task_0519_home_infusion_therapy/workspace/`. Directory assigned explicitly by the invocation (no index scan).

## Step 3: Copy shared files — 2026-06-30T15:04:30.000Z

Copied `INSTRUCTION.md` → `tasks/task_0519_home_infusion_therapy/workspace/INSTRUCTION.md`. (Done early; independent of scaffold.)

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-30T15:26:00.000Z

Note: first agent response was truncated by a connection error after writing SCAFFOLD.yaml; resumed via SendMessage to produce the two design files. Final result (all three files written, lint clean):

All three files are written and the lint is clean (512 calls scanned across §1.8+§1.9, all conform; all 14 FKs reverse-reachable).

I generated a complete **Expert-tier** scaffold for **Home Infusion Therapy (Option Care style)** and saved all three artifacts to the task directory.

**Difficulty tier:** Expert (per SKILL §0.4). Primary archetype *Ledger reconciliation* (estimate-vs-final claim adjudication on identical inputs) blended with secondary *Compliance/audit* (prior-auth, lab-monitoring gates, adverse-event holds, segregation of duties); flat topology, branching state machines, segregation-of-duties role model.

**SCAFFOLD.yaml counts:**
- **Entities:** 14 (DrugCatalog, PayerPlan, Nurse, Patient, Referral, InfusionOrder, PriorAuthorization, Compound, Pump, SupplyKit, NursingVisit, LabResult, AdverseEvent, Claim)
- **State machines:** 8 (Referral, InfusionOrder, PriorAuthorization, Compound, NursingVisit, SupplyKit, AdverseEvent, Claim) — includes a non-linear hold→resume cycle and a branching prior-auth fork-join
- **Calculations:** 7 (drug_line_allowed, per_diem_line, administered_days_count, copay_waterfall, ae_severity_score, pump_reservation_conflict, nurse_visit_conflict) with estimate/final dual variants
- **Validations:** 15 (priority-ordered)
- **Endpoints:** 55 (incl. `/_clock/set_current_utc` test-driving endpoint defaulting to 2026-05-01T00:00:00Z)
- **Error codes:** 15
- **RBAC roles:** 7 (IntakeCoordinator, Pharmacist, AuthSpecialist, VisitingNurse, MedicalDirector, Biller, WarehouseClerk)
- **Concurrency rules:** 1 (OCC on InfusionOrder.version for claim creation); plus 2 named conserved-quantity invariants

**Design instance counts:**
- **§1.8 difficulty design:** 18 instances — all 9 rules × 2 instances each
- **§1.9 corner design:** 44 instances (34 full test recipes + 10 `excluded_because:` stubs that cross-reference §1.8 by name)

**Validation:** `scaffold_lint.py` returns `VERDICT: clean lint` (512 §1.8+§1.9 calls scanned, all conform to §1.5; all 14 FKs reverse-reachable). All formula-derived assertions computed in code and pinned as literals (estimate allowed_total 136290 vs final 77880; copay OOP-cap clamp to 50000; round-half-up drug line 17446; AE severity threshold 7; pump 08:59 conflict / 09:00 clear; nurse 12:59 conflict / 13:00 clear; vial conservation 86→100). All 62 instance names unique; every `grounds` reference resolves.

One fix worth noting: original `api_prefix: /referrals` caused the lint's FK reverse-reachability check to fail for the flat topology; changed to `api_prefix: /` and added the missing reverse-reachability filters (`GET /patients?payer_plan_id`, `drug_id?` on orders, `payer_plan_id?` on auths/claims, `compound_id?` on visits, `visit_id?` on adverse-events), after which the lint passed clean.

Files verified: SCAFFOLD.yaml (1727 lines, no design keys), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1334 lines, single key), SCAFFOLD_CORNER_DESIGN.yaml (1513 lines, single key).

## Step 4: Generate PRD — 2026-06-30T15:35:00.000Z

The PRD has been generated at `workspace/PRD.md` (276 lines).

**Document stats:** 5 top-level sections (§1 Introduction, §2 Global Specifications with 10 subsections 2.1–2.10, §3 Business Logic with 12 subsections 3.1–3.12, §4 Endpoint Definitions, §5 Error Code Catalogue). 27 headings total, ~277 lines.

**Domain:** Home Infusion Therapy — ledger-reconciliation + compliance/audit (referral intake → specialty prior-auth → compounding/pump pairing → nursing visits → lab monitoring → adverse-event holds → estimate/final claim billing).

**Hard Contracts — all PASS:**
- Contract 1 (Field-Name Coverage): all 68 entity field names, 11 query/path params, `to_iso8601`+`disposition` inputs, 4 common fields, 30 state values, 25 enum values, 7 role names verbatim in backticks. (Initial audit caught a missing `to_iso8601`, added to §2.4.)
- Contract 2 (Rule Coverage): OCC on `expected_order_version`→`ERR_STALE_ORDER_VERSION` (412); segregation-of-duties; `sequence_index ≥ 4` trough-lab gate; AE severity formula (weights 2/1/3, threshold 7) with asymmetric hold cascade; whole-vial ceiling-before-discount drug line with single line-level half-up rounding; exact per-diem; deductible→coinsurance→OOP-cap waterfall; estimate-reads-vs-final-debits accumulators with void compensation; discontinuation cascade with vial-return; pump (1,440-min trailing, half-open) vs nurse (60-min symmetric, closed) interval geometry; validation priority ordering.
- Contract 3 (§3 Path Purity): zero slash-prefixed tokens / bare HTTP methods / method+path combos across 367 §3 backtick tokens.

§2.2 emitted verbatim from response-structure template. §4 table 4 columns; §5 table 2 columns.

**Confirmation:** neither design file was read/opened/grepped/referenced; no sibling task directories accessed.

## Step 6: Generate implementation — 2026-06-30T15:51:00.000Z

(Steps 5 and 6 launched concurrently; Step 6 finished first.)

Built a complete Python + Flask implementation at `workspace/implementation/`.

**Source files written:**
- `start.sh` — launcher (foreground, `exec`, install-guard)
- `requirements.txt`, `app.py` — entry point, blueprint registration, error handlers
- `clock.py` — logical clock (default `2026-05-01T00:00:00Z`, no wall-clock fallback)
- `db.py` — in-memory store + create/touch helpers
- `errors.py` — `ApiError` + 15 error-id constants
- `response.py` — `meta`/`response_type`/`data` envelope, private-field stripping
- `middleware.py` — `X-User-ID`/`X-User-Role` auth + RBAC
- `helpers.py` — body validation, ISO-8601 parsing, pagination (`limit`/`offset`/`total_count`/`has_more`)
- `services/calculations.py` — drug line, per-diem, copay waterfall, severity score, pump/nurse interval geometry
- `services/workflow.py` — administered_days recompute, auto-hold + future-visit MISSED sweep, discontinuation cascade with vial return, kit cancellation
- 10 route modules: reference, referrals, infusion_orders, prior_authorizations, compounds, supply_kits, nursing_visits, lab_results, adverse_events, claims

**start.sh:** reads `$PORT` (default 10000), binds `0.0.0.0`, `exec python3 app.py` foreground, pip-install guard on flask import.
**Storage:** in-memory dicts keyed by id, no seeding/preload — all list endpoints return `total_count: 0` on fresh boot.
**Endpoints implemented:** 55, matching PRD §4 table (incl. no-auth `/_clock/set_current_utc`).
**Verification:** 5 end-to-end smoke suites pass (RBAC, specialty auth, inventory/pump/nurse geometry, AE auto-hold + SoD, discontinuation cascade w/ vial return, estimate/final billing ledger w/ exact arithmetic, OCC stale-version, accumulator debit/void symmetry, lab-overdue gate, validation priority).
**Key fidelity decisions:** PRD §3.8 → discontinuation cascade also moves PICKING SupplyKits to CANCELLED (PRD wins over SCAFFOLD §1.2); PRD §2.8 → referenced-resource existence (404) checked before non-FK body validation (422).

## Step 5: Generate unit tests — 2026-06-30T15:59:00.000Z

Generated complete test infrastructure for the Home Infusion Therapy PRD benchmark task.

**Files written:** test_helpers/ = 9 files (`__init__.py`, `types.py` [15 entity TypedDicts + 11 enums], `api_client.py`, `api_errors.py` [15 error IDs + HTTP map], `assertions.py` [per-entity + ledger/inventory invariant checkers], `factories.py`, `constants.py`, `test_users.py` [opaque-role shared headers + mandatory entity-backed `make_visiting_nurse_headers`], `fixtures.py` [composite setup: draft/released/pending-auth/specialty orders, visit-driven activation, compounding w/ inventory draw, AE holds, posted claims]). test_suite/ = 9 files (`conftest.py` + `test_01`–`test_08`).

**Test functions emitted: 70**
- Queue A (Difficulty §1.8): 36 tests — all 18 difficulty instances × 2 tests each.
- Queue B (Corner §1.9): 34 tests — all 34 non-stub corner instances × 1 test each.

**Design instances SKIPPED: 0.** Every non-stub instance translated; all 10 `excluded_because` corner stubs correctly NOT translated. No instance failed the PRD-first two-condition filter.

**Verification:** all files compile; every test docstring carries exactly one valid `Design:` tag resolving to a real instance; all 86 PRD citation quotes satisfy C1 distinctive-≥8-word-substring grep criterion; every asserted `error_id` named with trigger in PRD §3; no skip/xfail; no scaffold leakage.

Verified on disk: 70 test functions, 70 Design tags, 9 test_helpers files, 9 test_suite files.

## Step 7: Test-and-fix loop — 2026-07-01T00:05:00.000Z

Clean exit. All 8 parallel rounds passed 70/70.

**Iterations run:** 2 (baseline sweep → 3 deterministic failures; second sweep → all green).

**Tests deleted:** None. All three failures resolvable as a genuine implementation bug or test-fixture bugs without weakening any PRD-required assertion.

**Fixes applied to `test_helpers/`:** None. The two test bugs lived in `test_suite/` (per-test inline setup), not shared helpers.

**Fixes applied to `test_suite/`:**
- `test_03_validations_and_errors.py` — `test_lab_overdue_blocks_fourth_visit`: added `clock="2026-06-20T00:00:00Z"` to setup. STEP 2 fixture bug. With default `2026-06-09` clock, the four visits (June 10–13) were future-dated, so the PRD §3.9 hold cascade ("sweeps every SCHEDULED visit whose start_at is in the future into MISSED") correctly marked the blocked 4th visit MISSED, contradicting `assert status == "SCHEDULED"`. Advancing the clock past all visits makes them past-dated, so the future-only sweep faithfully leaves the blocked visit SCHEDULED — keeping both `ERR_LAB_OVERDUE` and `SCHEDULED` assertions PRD-consistent.
- `test_05_order_workflows.py` — `test_visit_complete_blocked_when_order_on_hold`: changed v2 `start_at` from `2026-06-09T08:00:00Z` to `2026-06-08T08:00:00Z`. STEP 2 fixture bug. Test intent (past-dated visit not swept by future-only hold cascade) requires v2 in the past, but 08:00 June 9 is 8h after the 00:00 June 9 clock (future), so the sweep correctly marked it MISSED. June 8 makes it genuinely past-dated.

**Fixes applied to `implementation/`:**
- `routes/infusion_orders.py` — `create_order`: added referral-state guard rejecting order creation against a non-`ACCEPTED` referral with `ERR_INVALID_STATE`. STEP 3 implementation bug. PRD §3.2 ("Once a referral is `ACCEPTED`, a `Pharmacist` builds the infusion order against it") establishes the precondition and §2.8 names `ERR_INVALID_STATE` (HTTP 409); check placed after FK existence (priority 3) and body validity (priority 4) per §2.8 ordering.

**Final sweep:** all 8 parallel rounds passed == total at 70/70, failed=0, zero union failures across rounds (no flakiness).

Note: orchestrator re-ran an independent 8-round verification sweep afterward because the subagent's `results.{1..8}.json` were not present on disk at hand-off (see Step 7-verify below).

## Step 8: Finalize PRD — 2026-07-01T00:08:00.000Z

The patch is complete. PRD_FINALIZED.md contains exactly one minimal edit, traceable to the single `implementation/` fix in the Step 7 diff. The two test_suite fixture bugs were correctly identified as needing no PRD edit because the PRD already uniquely determines the future-only hold-cascade sweep.

---

## Summary

**Line counts:** PRD.md = 276 lines; PRD_FINALIZED.md = 276 lines (same line, expanded inline). %-delta in lines: 0%. The single changed line grew from ~1130 to ~1500 characters (~+33% on that line).

**Changes (one bullet per change):**
- §3.2 — insert — Pinned that order creation requires the referenced referral to be in `ACCEPTED`, rejecting any other referral state with `ERR_INVALID_STATE`, and placed the check as a priority-5 state-legality check per §2.8 (after FK existence and body validity) — `routes/infusion_orders.py:43-48`.

**Step 7 items that required NO PRD edit (per Method step 1):**
- test_03 `test_lab_overdue_blocks_fourth_visit` — pure STEP 2 fixture bug (clock setup). PRD §3.9 already uniquely determines the future-only sweep ("sweeps every `SCHEDULED` visit ... whose `start_at` is in the future into `MISSED`"), matching `workflow.py:29-38`. No silence/mismatch.
- test_05 `test_visit_complete_blocked_when_order_on_hold` — pure STEP 2 fixture bug (v2 `start_at`). Same PRD §3.9 future-only sweep already pinned. No silence/mismatch.

**Per-edit pre-edit search log:**

Edit 1 (§3.2 referral-state guard):
- (a) **Subject identified:** The precondition that infusion-order creation requires an `ACCEPTED` referral, and the error/priority used when it is not — `ERR_INVALID_STATE` at validation priority 5.
- (b) **Impl paths enumerated and read/grepped:** Grepped `invalid_state|ACCEPTED|referral[` across all `routes/*.py` and `services/*.py`. Read `routes/infusion_orders.py` in full (create_order lines 18-64 = Step 7 site; plus submit/discontinue/complete which use `ERR_INVALID_STATE` for order-state legality, lines 102/120/132). Read `routes/referrals.py` accept/reject state machine (lines 64-82) confirming `ACCEPTED` is reachable only from `RECEIVED` and `REJECTED` is terminal — consistent with "any other state" including `RECEIVED`/`REJECTED`. Verified `ERR_INVALID_STATE` is used uniformly system-wide for "state from which the transition is not defined" (prior_authorizations, claims, compounds, supply_kits, nursing_visits, adverse_events) — consistent with §2.8. Confirmed the create_order FK-existence checks (lines 25-28) and body-validity checks (lines 36-41) precede the referral-state check (lines 47-48), matching the priority 3 → 4 → 5 ordering I wrote.
- (c) **Wording adjustment:** Phrased the rejection as "a referral in any other state" rather than enumerating specific states, so the sentence remains correct for every non-`ACCEPTED` referral status (`RECEIVED`, `REJECTED`) without over-claiming a fixed enumeration. Anchored priority explicitly to §2.8 to avoid implying the referral-state check runs before FK resolution or body validation (which would contradict the impl's actual ordering).

## Step 9: Complete PRD — 2026-07-01T00:14:00.000Z

All eight edits are in place. The task is complete. Here is my summary.

## Summary

**Source vs output:** `PRD_FINALIZED.md` (the latest PRD, present) was copied to `PRD_COMPLETED.md` and edited in place.
- Line counts: 276 → 276 (every edit is in-paragraph; no new sections/paragraphs/lines added).
- Char count: 42,455 → 45,258 bytes (**+2,803 chars**).

**Counts:** 8 changes total — **7 ambiguity-pins**, **1 mismatch-revision**.

**Per-change log** (`{section} — {type} — {class} — {what} — {impl ref}`):

- §2.3 Pagination — insert — ambiguity — Pinned that a `limit` below 1 is raised to 1, a negative `offset` is raised to 0 (clamp, not reject), and a non-integer `limit`/`offset` is rejected with `ERR_INVALID_REQUEST`, and that `meta` reports the clamped values — `helpers.py:118-139`.
- §2.3 Pagination — insert — ambiguity — Pinned that list endpoints accept optional foreign-key filter query params (per-entity FK fields) and ignore unrecognized params — `routes/*.py` list handlers (e.g. `compounds.py:56-61`, `infusion_orders.py:81-89`).
- §2.3 Pagination — insert — ambiguity — Pinned the `created_at` tie-break: ties broken by ascending internal creation order for deterministic ordering — `helpers.py:150-152`, `db.py:46-47`.
- §2.4 Logical clock — insert — ambiguity — Pinned that the clock endpoint is auth/role exempt, accepts any caller, and returns 200 with `data.now` (ISO 8601 UTC, 3 fractional digits) — `routes/reference.py:25-34`, `middleware`-bypass.
- §3.4 Compounding — revise — mismatch — Pinned that a non-`AVAILABLE` pump (e.g. `RETIRED`) also yields `ERR_PUMP_DOUBLE_BOOKED`, and that the pump check runs before inventory before auth-units (the §2.8 order the impl follows, which the §3.4 prose previously narrated in the opposite order) — `routes/compounds.py:85-112`.
- §3.6 Visit scheduling — insert — ambiguity — Pinned that each new visit re-derives every sibling's `sequence_index` and that this re-sequencing does not bump siblings' `version`/`updated_at` — `routes/nursing_visits.py:19-24,82`.
- §3.7 Lab-monitoring gate — insert — ambiguity — Pinned the lab-due horizon as exactly **14 days** with both boundaries inclusive (PRD left the day count unstated) — `services/calculations.py:16,81-83`.
- §3.12 Billing / per-diem line — insert — ambiguity — Pinned that a missing `therapy_category` entry in `per_diem_rate_cents` yields a rate of 0 — `services/calculations.py:36-39`.
- §3.12 Billing / claim create — insert — ambiguity — Pinned that `expected_order_version` is retained on the claim and echoed back as a same-named field — `routes/claims.py:64`.

**Notes on things deliberately left unchanged:** RBAC for all endpoints matches §4 exactly; all calculation formulas (whole-vial ceiling, severity score, copay waterfall, pump/nurse overlap geometry, rounding points) and accumulator post/void symmetry already match the PRD uniquely. Two impl behaviors that are effectively unreachable were not pinned to avoid inventing contract: the referral-accept "patient not ACTIVE → `ERR_INVALID_STATE`" branch (no discharge endpoint exists, so patients are never non-ACTIVE) and `updated_at == created_at` at creation (conventional, non-load-bearing). The 404/405 framework fallback to an `ERR_NOT_FOUND` envelope is infra-level, not a PRD-described surface.
