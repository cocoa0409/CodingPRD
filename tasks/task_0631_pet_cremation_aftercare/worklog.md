# Worklog — task_0631_pet_cremation_aftercare

## Step 1: Create Task Directory — 2026-06-22T17:29:39.000Z

Created `tasks/task_0631_pet_cremation_aftercare/` and `tasks/task_0631_pet_cremation_aftercare/workspace/` (pre-allocated ID; no auto-numbering scan performed). Verified `./INSTRUCTION.md` exists for Step 3 copy.

## Step 2: Generate Scaffold — 2026-06-22T17:50:06.000Z

Generated a fresh Expert-difficulty scaffold for **Pet Cremation & Aftercare Provider** (no sibling tasks consulted) into `/home/ubuntu/github/CodingPRD/tasks/task_0631_pet_cremation_aftercare/`:

- `SCAFFOLD.yaml` — §1.0–§1.7 plus complexity profile (no design keys) — 1454 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — §1.8, single `scaffold_difficulty_design` key — 1422 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` — §1.9, single `scaffold_corner_design` key — 1699 lines

**Complexity profile:** workflow_orchestration + quota_allocation; hybrid topology; parallel state-machine shape; peer_roles; immediate consistency. Layers: cascading side effects, dual-variant calculation, optimistic concurrency, scheduled/deferred actions, derived-field reconciliation.

**Scaffold contents:**
- **Entities:** 13 (Clinic, PetOwner, Cooler, Retort, CremationBatch, Case, TransportLeg, CustodyEvent, KeepsakeOrder, CertificateRecord, ReturnRoute, MemorialAddon, Invoice)
- **State machines:** 9 — including Case's two parallel axes (custody_status × billing_status), branching fork-join CremationBatch (PRIVATE vs COMMUNAL), cyclic Cooler (AVAILABLE↔FULL), plus linear-with-revert machines for TransportLeg/ReturnRoute/Invoice/KeepsakeOrder/MemorialAddon
- **Concurrency:** 1 OCC rule (invoice-create-stale-case, `expected_case_version`, 412)
- **Calculations:** 6 (weight_tier, case_cremation_charge with private/communal variants, invoice_total with owner/clinic variants, clinic_statement_balance with accrual/completion variants, cooler_occupancy, clinic_outstanding_balance)
- **Validations:** 15 priority-ordered rules
- **Endpoints:** 50 (includes `/_clock/set_current_utc` with default 2026-01-01T00:00:00Z; all FKs have reverse-reachability GETs)
- **Error catalog:** 19 codes
- **RBAC roles:** 4 (CrematoryAdmin & CrematoryOperator opaque; ClinicStaff entity_backed:Clinic; PetOwner entity_backed:PetOwner)

**Design instances:**
- §1.8 difficulty: **19 instances** across all 9 rules (each ≥2; combinatorial_formula has 3 covering modes a/b/c)
- §1.9 corner: **44 instances** (37 active test recipes + 7 `excluded_because` stubs, each citing a valid §1.8 instance)

**Validation status:** `scaffold_lint.py` → `VERDICT: clean lint`. All grounds references resolve, all numeric asserts pre-computed as literals, no forbidden concurrency vocabulary, no design keys leaked into SCAFFOLD.yaml, names unique across the §1.8/§1.9 union.

## Step 3: Copy Shared Files — 2026-06-22T17:50:31.000Z

Copied `INSTRUCTION.md` → `tasks/task_0631_pet_cremation_aftercare/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-22T17:56:39.000Z

Generated `workspace/PRD.md` (291 lines, 44544 bytes) from `SCAFFOLD.yaml` only.

**Document stats:** 5 top-level sections (Introduction; Global Specifications; Business Logic & Workflows; Endpoint Definitions; Error Code Catalogue); 10 §2 subsections; 14 §3 subsections; 51-row endpoint table; 19-row error table.

**Hard contracts — all PASS:**
- Contract 1 (Field-Name Coverage): all 63 entity field names + every endpoint request-body/query-param/path-param identifier appear verbatim. 0 missing.
- Contract 2 (Rule Coverage): all 19 error IDs in narrative; all custody/billing/batch/cooler/transport/route/invoice/keepsake/memorial state values and enum values present; OCC rule expresses write_endpoint + expected_case_version + ERR_STALE_CASE_VERSION (412); all calculations rendered in precise prose; constants embedded.
- Contract 3 (§3 Path Purity): 458 §3 backtick tokens, 0 paths/methods leaked.

**File access confirmation:** read only `SCAFFOLD.yaml` (plus skill reference files); did NOT open/grep/reference `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`.

## Step 5: Generate Unit Tests — 2026-06-22T18:11:09.000Z

**Test files written:** 6 test files (plus `conftest.py`) in `test_suite/`:
- `test_01_pricing_and_calculations.py` (10 tests)
- `test_02_custody_and_billing_workflows.py` (13 tests)
- `test_03_validations_and_constraints.py` (12 tests)
- `test_04_invoicing_invariants_and_concurrency.py` (8 tests)
- `test_05_resources_and_access.py` (11 tests)
- `test_06_difficulty_second_pass.py` (19 tests)

**Total test functions emitted:** 73 (all collect cleanly under pytest; all imports resolve).

**Queue A (Difficulty) translated:** 19 instances (9 rules; `combinatorial_formula` has 3 instances, the rest 2 each), each covered by exactly 2 tests = 38 tests. Every difficulty instance meets the ≥2-tests requirement.

**Queue B (Corner) translated:** 35 of 37 non-stub instances, each covered by 1 test = 35 tests. The 7 `excluded_because` stubs were correctly not translated.

**Instances skipped (2), both queue B:**
- Default-value silence: `Corner/endpoints/ep_clinic_statement_default_basis` — asserts `basis == COMPLETION` when omitted, but PRD §3.14 names only the two allowed values and states no server-side default; not uniquely derivable.
- Unique-derivability failure: `Corner/state_machines/sm_communal_case_finalize_return_rejected` — asserts `/ready-return` on a COMMUNAL CREMATED case → ERR_INVALID_STATE, but PRD §3.8 places the explicit PRIVATE-only restriction on finalize-return, not ready-return.

**test_helpers/ files written (9):** `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`.

## Step 6: Generate Implementation — 2026-06-22T18:11:09.000Z

Generated Python + Flask implementation at `workspace/implementation/`.

**Files:** `start.sh` (executable, foreground, guarded dep install), `requirements.txt` (Flask==3.0.3), `app.py` (50 endpoints, error handlers, RBAC + ownership scoping, validation precedence), `services.py` (state machines, calculations, cascading side effects), `models.py` (entity constructors/serializers, pricing catalogs, weight-tier + audit-field logic), `db.py` (in-memory store, UUID + sequence + certificate counters, logical clock), `clock.py` (logical clock, default 2026-01-01T00:00:00Z), `response.py` (envelope helpers), `middleware.py` (X-User-ID/X-User-Role auth), `validation.py` (body-field + pagination), `errors.py` (error catalog → HTTP status).

**Runtime:** Python 3.14.4, Flask 3.0.3. `app.run(host="0.0.0.0", port=int(os.environ.get("PORT","10000")), threaded=True)`. start.sh: `cd "$(dirname "$0")"`, guarded `pip install`, then `exec python3 app.py`.

**Storage:** in-memory only (Python dicts in `db.py`'s single `Store()`), no SQLite/JSON/disk, no seeding — fresh boot returns empty collections.

**Implementer-pinned (from SCAFFOLD detail, PRD-silent): clinic-statement default basis = COMPLETION; viewing-room 15-min buffer applied to both intervals.** (Step 8/9 will reconcile PRD.)

## Step 7: Run Tests and Iterate — 2026-06-22T18:39:17.000Z

**Iterations run:** 3 fix-and-sweep iterations, then 2 additional confirmation sweeps. Final state: 3 consecutive clean 8-round parallel sweeps (24 rounds total), each 73/73 passing with 0 failures and 0 errors. Orchestrator ran an independent 4th confirmation 8-round sweep: all 8 rounds 73/73, 0 failed, 0 errors (results.{1..8}.json persisted).

**Starting state:** 71/73 passing in every round, with 2 deterministic logic failures. A flakiness signal emerged only after the logic fixes — intermittent server boot-timeout errors (1-2 errored rounds per 8-round sweep), which the parallel sweep correctly surfaced.

**Tests deleted:** None. Both initial failures were genuine bugs (one in the implementation, one in the test suite); neither hit a PRD-silence or non-unique-derivability condition.

**Fixes applied to test_suite/:**
- `test_04_invoicing_invariants_and_concurrency.py` :: `test_pay_owner_billed_invoice_no_clinic_change` — STEP 2 assertion mis-translation. Test expected `total_cents == 19500` ("1500 mid-tier fee"), but PRD §3.10 states the owner handling fee is "2500 cents when the subtotal is below 20000 cents". The subtotal here is 18000 (MEDIUM tier, weight 50), which is below 20000, so the correct fee is 2500 and total 20500. Corrected the expected value and comment to match PRD. The PRD-faithful implementation was already producing 20500.

**Fixes applied to implementation/:**
- `services.py` :: `case_cancel` — STEP 3 implementation bug. The transport-leg cancel cascade only moved legs in `("ASSIGNED", "EN_ROUTE")` to CANCELLED, leaving ARRIVED legs untouched. PRD §3.13 states "Any transport leg not already cancelled is moved to `CANCELLED`" (unambiguous quantifier "Any"; the §3.3 terminal-state language governs only the operator's explicit PATCH transitions, a distinct code path). Changed the guard to cancel every leg whose status is not already `CANCELLED`.
- `app.py` :: `_serve` (new) + `requirements.txt` + `start.sh` — stability fix for the boot-timeout flakiness. Switched from Flask's dev server to waitress (added `waitress==3.0.2` to requirements). The new server binds its own listening socket with `SO_REUSEADDR` and a short bind-retry loop, then hands the bound socket to waitress — closing the kill-then-respawn port race (a SIGKILLed predecessor's socket briefly lingering) that was causing "API server could not be restarted" errors under 8× concurrent per-test reboots. Also replaced `start.sh`'s dependency probe `python3 -c "import flask, waitress"` (~1s) with `importlib.util.find_spec` (~0.1s) to cut redundant CPU off every boot. Storage remains in-memory only; no seeding.

**Key finding:** The two logic failures were deterministic; the boot-timeout flakiness was timing-sensitive and only appeared intermittently across rounds — exactly the class of bug the 8-round parallel sweep is designed to catch.

## Step 8: Finalize PRD — 2026-06-22T18:41:57.000Z

**Line counts:** PRD.md = 291 lines, PRD_FINALIZED.md = 291 lines. **%-delta = 0%** (byte-identical, verified via `diff`).

**Changes:** Zero edits. PRD_FINALIZED.md is a verbatim copy of PRD.md.

**Per-item disposition (all three Step 7 diff items → no-edit):**
1. `case_cancel` transport-leg cascade fix (services.py:232-235) — no PRD edit. Impl now cancels every leg not already `CANCELLED` (incl. `ARRIVED`); PRD §3.13 already states "Any transport leg not already cancelled is moved to `CANCELLED`." Impl bug fixed to match already-correct PRD.
2. `test_suite` fee fix (test_04) — no PRD edit. Impl handling-fee logic (2500 if subtotal<20000; 1500 if 20000≤subtotal≤50000; 0 if >50000) matches PRD §3.10. Test had wrong expected value; correcting it aligned the test to PRD+impl.
3. waitress server change (app.py/requirements.txt/start.sh) — no PRD edit. Pure infrastructure/boot-mechanics stability fix, no PRD-observable behavior.

Pre-edit search performed for the one behavioral candidate (case_cancel cascade): enumerated make_transport_leg, transport_leg_transition/patch_transport_leg (operator PATCH path, ARRIVED terminal), case_receive (reads ARRIVED, no mutation), case_cancel cascade — PRD §3.13 wording already consistent with all paths; no edit committed.

## Step 9: Complete PRD — 2026-06-22T18:45:58.000Z

Source: PRD_FINALIZED.md → PRD_COMPLETED.md. Lines 291 → 291 (all edits in-paragraph). Chars 44,544 → 45,637 (+1,093).

**Counts:** Ambiguity-pins: 4. Mismatch-revisions: 1.

**Changes:**
- §2.3 (Pagination/list ordering) — insert — ambiguity — list-sort ties on equal `created_at` (common under frozen logical clock) broken by creation order, earliest-created first — app.py:92 (`sorted_by_created` keys on `(created_at, _seq)`).
- §3.6 (Certificate record) — insert — ambiguity — `certificate_number` is a server-wide monotonic counter rendered as a decimal string starting at `"1"`, incrementing by one — db.py:49-51 / models.py:380.
- §3.9 (Communal allocation) — insert — ambiguity — "last member" who absorbs the rounding remainder, when members share identical `created_at`, resolved by creation order (most recently created is last) — services.py:52,64.
- §3.12 (Viewing room scheduling) — revise — mismatch — both the new and each existing viewing window are extended by the 15-minute buffer on each side, compared as half-open intervals (touch-after-buffer does not collide) — services.py:445-461.
- §3.14 (Clinic statement) — insert — ambiguity — default basis is `COMPLETION` when `basis` omitted; any other value yields `ERR_INVALID_REQUEST` (422) — app.py:165-167.

Both implementer-flagged silences pinned: (a) clinic-statement default basis = COMPLETION; (b) viewing-room buffer applied to both intervals.

Deliberately left unchanged (not stated-prose ambiguities): additive list-filter query params; `api_request_timestamp` sourced from wall-clock (PRD §2.9 closed clock-sourced set excludes request metadata); unspecified `custodian` strings on custody events PRD never pins.

## Pipeline Complete — 2026-06-22T18:45:58.000Z

All 9 steps finished. Final state: **73/73 tests passing across an independent 8-round parallel stability sweep** (results.{1..8}.json all `passed=73 failed=0 errors=0 total=73`). 0 tests deleted. PRD_COMPLETED.md is the canonical contract.
