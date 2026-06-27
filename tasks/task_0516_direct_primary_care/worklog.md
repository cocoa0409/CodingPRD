# Worklog — task_0516_direct_primary_care

## Step 1: Create task directory — 2026-06-27T00:00:00.000Z

Created `tasks/task_0516_direct_primary_care/` with `workspace/` subdirectory (pre-allocated index 0516, used as-is per instructions). Difficulty target: Expert (§0.4 Expert tier, 10-15 entities).

## Step 2: Generate scaffold — 2026-06-27T00:00:00.000Z

All three files are complete, parse cleanly, lint clean, and satisfy the structural requirements. The scaffold is at Expert difficulty with 13 entities and tightly-coupled mechanics.

Generated all three scaffold artifacts for **task_0516_direct_primary_care** (Direct Primary Care / Concierge Membership), built fresh from the scenario + skill spec only (no sibling tasks consulted). All files parse and `scaffold_lint.py` reports `VERDICT: clean lint` (495 §1.8+§1.9 calls validated, all FKs reverse-reachable).

**Complexity profile:** Expert tier. Primary archetype *ledger reconciliation* (insurance-vs-DPC split) + secondary *quota/allocation* (panel/seat capacity); layers: optimistic concurrency, cascading side effects, dual-variant calculation, derived-field reconciliation, scheduled actions; hybrid topology, parallel/cyclic/branching state shapes, peer roles, immediate consistency.

**Counts:**
- **Entities:** 13 — Practice, Provider, Employer, Member, Membership, EmployerSeat, VisitSlot, Visit, CarePlan, Referral, MessageThread, Invoice, Payment
- **State machines:** 6 — Member (branching grace/reinstate cycle), Visit (parallel clinical_status × billing_status dimensions), CarePlan (ACTIVE↔UNDER_REVISION cycle), Referral (branching), Invoice (linear-with-revert compensation), MessageThread (branching)
- **Concurrency rules:** 2 (OCC) — `visit-book-stale-slot` (VisitSlot.version), `seat-occupy-stale-employer` (Employer.version)
- **Calculation rules:** 5 — invoice_split (dual variant), member_monthly_share (tiered, discount-before-sponsorship), membership_proration, panel_assignment_selector, thread_sla_deadline
- **Validation rules:** 16 (priority-ordered)
- **Endpoints:** 62 (includes business CRUD/action endpoints, FK reverse-reachability GETs, and 2 test-driving endpoints: `/_clock/set_current_utc` with default `2026-05-01T00:00:00Z`, `/_billing/run_suspension_sweep`)
- **Error codes:** 17
- **Roles:** 5 — PlatformAdmin (opaque), Provider/Member/Employer (entity_backed), Anonymous (opaque)
- **§1.8 difficulty instances:** 18 (all 9 rules × 2)
- **§1.9 corner instances:** 41 total = 36 active + 5 `excluded_because` stubs, spanning all 9 sections

## Step 3: Copy shared files — 2026-06-27T00:00:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_0516_direct_primary_care/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-27T00:00:00.000Z

Generated `workspace/PRD.md` (315 lines) from `SCAFFOLD.yaml`. Read only the skill spec, §2.2 source, the example PRD, and `SCAFFOLD.yaml` — neither withheld design file opened.

Section structure: §1 Introduction; §2 Global Specifications (RBAC/5 roles, response structure verbatim, pagination, common properties, hierarchical consistency/cascades, OCC, insurance-vs-DPC split, monetary precision, logical clock & sweeps); §3 Business Logic (14 subsections); §4 Endpoint Definitions (62 rows); §5 Error Code Catalogue (17 rows).

Coverage confirmation (all mechanically verified): 71/71 entity fields, 43/43 request-body identifiers, 21/21 query params, 17/17 error IDs, 5/5 roles, 48/48 state/enum values, 5/5 calculations (both variants each). Hard Contracts: Field coverage PASS, Rule coverage PASS, Path purity PASS (§3 has 0 path tokens). §2.2 verbatim verified.

## Step 5: Generate unit tests — 2026-06-27T00:00:00.000Z

Generated complete test infrastructure. **Test files (10) in `test_suite/`:** 72 tests total, all collect cleanly.
- test_01_billing_calculations.py (8); test_02_visit_and_careplan_lifecycle.py (8); test_03_cascades_and_invariants.py (8); test_04_slot_booking_conflicts.py (8); test_05_proration_and_charges.py (5); test_06_entities_crud.py (9); test_07_state_machines.py (6); test_08_sla_and_panel_calculations.py (5); test_09_validations_and_constraints.py (6); test_10_errors_rbac_concurrency.py (10).

Coverage: Queue A (Difficulty) all 18 instances × 2 tests (36); Queue B (Corner) all 36 non-stub instances × 1 test (36). Skipped: 0 — every non-stub instance passed the PRD-first two-condition filter. 5 `excluded_because` corner stubs correctly NOT translated.

test_helpers/ files (9): __init__.py, types.py, api_client.py (68 endpoint methods), api_errors.py (16 errors + HTTP-status), assertions.py, factories.py, constants.py, test_users.py, fixtures.py. Every docstring carries exactly one Design: tag resolving to a real instance; PRD citations verified verbatim; Payment TypedDict omits updated_at/version; no skip/xfail.

## Step 6: Generate implementation — 2026-06-27T00:00:00.000Z

Generated Python 3 + Flask REST API at `workspace/implementation/`. State purely in-memory (one module-level dict per entity in db.py; logical clock in clock.py defaulting to 2026-05-01T00:00:00Z). No SQLite/files/seeding — boots empty every process start.

Endpoint count: 62 distinct (method, path) routes — complete match to PRD §4. start.sh reads $PORT (default 10000), binds 0.0.0.0, runs foreground (exec python3 app.py), guards pip install for fast reboots.

Files: start.sh, requirements.txt, app.py, db.py, clock.py, errors.py, response.py, middleware.py, serialize.py, validate.py, timeutil.py, routes/{__init__,helpers,practices,providers,employers,members,memberships,visits,care_plans,referrals,message_threads,invoices,payments,admin}.py, services/{__init__,domain,money}.py.

Behaviors: response envelope/req_ ids/ISO-8601 UTC/pagination; auth X-User-ID/X-User-Role, 5 roles, validation priority order with exact error IDs; membership lifecycle, parallel Visit dimensions, CarePlan cyclic revision, Referral branching+expiry, MessageThread SLA+escalation; all 5 calculations via Decimal ROUND_HALF_UP; OCC on expected_slot_version/expected_employer_version → 412 ERR_STALE_VERSION; cascades (panel recompute, slot booked_count/state, employer occupied_seat_count). Smoke suites passed on fresh boot.

## Step 7: Run tests and iterate — 2026-06-27T00:00:00.000Z

All 8 parallel rounds now pass cleanly: 72/72 in every round, zero failures, zero errors. Clean sweep achieved.

**Iterations run:** 2 (initial sweep + 1 fix + confirming sweep).

**Diagnosis:** The initial sweep showed exactly one test failing identically across all 8 rounds — `test_thread_after_hours_deadline_four_hours` in `test_08_sla_and_panel_calculations.py`. The failing test created a message thread at 20:00Z (UTC hour 20 ≥ 18 → `AFTER_HOURS`) and asserted `response_deadline` started with `2026-06-01T22:00:00` (created_at + 2 hours). PRD §3.12 states verbatim: "an `AFTER_HOURS` thread's `response_deadline` is its `created_at` plus 4 hours." So 20:00 + 4 = `2026-06-02T00:00:00`, which is exactly what the implementation returned. This was a STEP 2 TEST-vs-PRD CONSISTENCY bug: the test's expected value contradicted the PRD rule it cited. PRD uniquely determines the outcome, so the test stays and the assertion was corrected.

**Tests deleted:** None.

**Fixes applied to test_helpers/:** None.

**Fixes applied to test_suite/:**
- `test_suite/test_08_sla_and_panel_calculations.py`, `test_thread_after_hours_deadline_four_hours` — corrected the expected `response_deadline` from `2026-06-01T22:00:00` (created_at + 2h, contradicting PRD) to `2026-06-02T00:00:00` (created_at + 4h, per PRD §3.12's "plus 4 hours"). Comment updated.

**Fixes applied to implementation/:** None — the implementation (`services/domain.py:compute_thread_sla`) already correctly applied the 4-hour AFTER_HOURS deadline.

**Final state:** 8/8 parallel rounds pass with 72/72 tests each, no flakiness.

## Step 8: Finalize PRD — 2026-06-27T00:00:00.000Z

`PRD_FINALIZED.md` produced as an exact copy of `PRD.md` with **zero edits**. PRD.md = 315 lines, PRD_FINALIZED.md = 315 lines, 0% delta (byte-identical, confirmed via diff).

The single Step 7 diff item was a test-bug correction in `test_thread_after_hours_deadline_four_hours`: the test asserted created_at + 2h, contradicting the PRD rule it cited. That rule is already verbatim-present and correct in PRD §3.12 ("an `AFTER_HOURS` thread's `response_deadline` is its `created_at` plus 4 hours"), and the implementation already matches it. No PRD silence and no PRD/impl mismatch to patch — pure fixture-vs-PRD consistency correction.

Pre-edit search (subject: message-thread SLA priority + response_deadline, §3.12/§3.13): enumerated `services/domain.py` compute_thread_sla (8≤hour<18 → ROUTINE/+24h, else AFTER_HOURS/+4h), `routes/message_threads.py` creation+reply guard, `routes/admin.py` sweep Pass 3 escalation — all consistent with unmodified PRD prose. No edit warranted.

## Step 9: Complete PRD — 2026-06-27T00:00:00.000Z

I built `PRD_COMPLETED.md` by overwriting it with a clean copy of `PRD_FINALIZED.md` and then applying minimal inline pins. (Note: the pre-existing `PRD_COMPLETED.md` was a stale, partially-pinned file; I re-copied from `PRD_FINALIZED.md` to guarantee the baseline is the documented source, then re-applied all needed pins.)

**Counts**
- Source `PRD_FINALIZED.md`: 315 lines, 52,334 chars
- Output `PRD_COMPLETED.md`: 315 lines, 55,414 chars (char delta +3,080)
- 12 lines revised, all in-place (no lines/sections added or removed)
- Ambiguity-pins: 8 · Mismatch-revisions: 4

**Changes** (`{section} — {action} — {kind} — {what} — {impl ref}`)

- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall-clock — `implementation/response.py:21`
- §2.3 — insert — ambiguity — list ordering breaks `created_at` ties (frequent under the static clock) by persistence order — `implementation/validate.py:104`
- §2.4 — revise — ambiguity — `version` initial value pinned to 1 (was "its initial value") — `implementation/db.py:46`
- §3.3 — insert — ambiguity — PCP reassignment of an ACTIVE/PAST_DUE member also recomputes the prior provider's panel fields — `implementation/routes/members.py:138-141`
- §3.4 — insert — ambiguity — auto-assign breaks a `created_at` tie by persistence order (still never by `id`) — `implementation/services/domain.py:239`
- §3.5 — insert — ambiguity — `virtual_capacity` below 1 → `ERR_VALIDATION` — `implementation/routes/providers.py:135`
- §3.6 — insert — ambiguity — no-show before slot `ends_at` → `ERR_INVALID_STATE` — `implementation/routes/visits.py:222-223`
- §3.7 — revise — mismatch — `insurance_billed_cents` is always present and is 0 for uninsured (was "populated only for an insured member") — `implementation/services/domain.py:191,198-203`
- §3.8 — revise — mismatch — share recompute list corrected: at registration/activation/rollover/reinstatement/occupy; seat *release* does NOT recompute (dropped "or releases") — `implementation/services/domain.py:262-276`, `routes/members.py:66`, `routes/employers.py:184`
- §3.8 (membership charge) — revise — mismatch+ambiguity — negative `amount_cents`/non-`MEMBERSHIP_FEE` `charge_kind` → `ERR_INVALID_REQUEST`; `wallet_applied_cents` computed and recorded regardless of outcome but balance debited only on success; SUCCEEDED-state check precedes amount/PCP checks; PAST_DUE late fee in amount; FAILED only ACTIVE→PAST_DUE at period end else no-op — `implementation/routes/memberships.py:70-137`
- §3.8 (invoice charge) — revise — mismatch+ambiguity — negative `amount_cents` → `ERR_INVALID_REQUEST`; no `charge_kind` accepted; wallet computed/recorded regardless of outcome; FAILED leaves invoice ISSUED and wallet unchanged — `implementation/routes/invoices.py:61-104`
- §3.14 — insert — ambiguity — value-range/positivity/within-practice-uniqueness violations on well-typed fields → `ERR_VALIDATION`, evaluated after well-formedness/existence (covers `npi`, `email`, and all numeric-range fields) — `implementation/routes/practices.py:33-46`, `providers.py:33,38`, `employers.py:29-32`, `members.py:40`, `care_plans.py:33,90`

**Items checked and left unchanged** (PRD already pins them): §2.4 Payment-only-fields, §3.9 proration formula/boundaries, §3.7 split arithmetic and aggregate rounding, §3.12 SLA priority/deadline boundaries, §3.13 sweep three passes, OCC version guards, RBAC ownership, the AMOUNT_MISMATCH-before-PCP_REQUIRED ordering, and the reply-after-deadline error (`ERR_INVALID_STATE`, added to §3.12 along the way). Booking with a null assigned PCP (visit `provider_id` copied as null) was judged adequately implied by existing prose and left alone to avoid over-specifying.
