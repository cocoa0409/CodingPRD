# Worklog — task_0623_dermatology_practice

## Step 1: Create Task Directory — 2026-06-22T11:33:00.000Z

Created `./tasks/task_0623_dermatology_practice/workspace` via `mkdir -p`. Task dir = `./tasks/task_0623_dermatology_practice`. Difficulty band: Expert.

## Step 2: Generate Scaffold — 2026-06-22T11:55:00.000Z

Generated three-file scaffold for **Task 0623 — Dermatology Practice (medical & cosmetic)** at the **Expert** difficulty band, written purely from the scenario and the skill spec (no sibling tasks consulted). All three files parse cleanly and `scaffold_lint.py` returns **`VERDICT: clean lint`** (286 calls scanned, all conform to §1.5; all FKs reverse-reachable).

**Files written:** `SCAFFOLD.yaml` (§1.0–§1.7), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`), `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`).

**Design profile:** ledger-reconciliation (insurance-vs-cash split) blended with compliance/audit (prior-auth + step therapy); flat topology (`api_prefix: /`); parallel/cyclic/compound state machines; peer_roles. Layers: dual-variant calc, cascading side effects, OCC, scheduled actions, derived-field reconciliation.

**Counts:**
- **Entities:** 13 (Provider, Room, Patient, Encounter, SkinExamPhoto, Biopsy, ProcedureBooking, PriorAuthorization, StepTherapyTrial, CosmeticMembership, CosmeticTreatment, Charge, RecallReminder)
- **State machines:** 8 (incl. Encounter as two parallel dimensions clinical×billing; Biopsy branching on result; PriorAuthorization cyclic DENIED→SUBMITTED; CosmeticMembership compound auto-EXHAUSTED)
- **Concurrency rules:** 2 OCC (membership-redeem stale version, room-booking stale version)
- **Calculations:** 9 (dual-variant insurance/cash split; silver/gold wallet split; biologic tiered pricing with resubmission step-down; deductible waterfall with pinned per-charge rounding; order-pinned cosmetic total; step-therapy count; wallet grant; two recall horizons)
- **Validations:** 17 (priority-ordered, incl. distinct room half-open+buffer vs provider closed-interval overlap)
- **Endpoints:** 60 (incl. `/_clock/set_current_utc` default `2026-01-01T00:00:00Z`, `/_recall/sweep`)
- **Error catalog:** 39
- **RBAC roles:** 5 (PracticeAdmin/FrontDesk/PathLab/BillingSpecialist opaque; Provider entity-backed)
- **Difficulty design:** 18 instances (all 9 rules × 2). **Corner design:** 31 active instances + 5 `excluded_because` stubs.

## Step 3: Copy INSTRUCTION.md — 2026-06-22T11:55:30.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-22T12:01:00.000Z

Generated `workspace/PRD.md` (324 lines, 5 top-level sections, 19 subsections). Hard contracts: field coverage PASS (66/66), rule coverage PASS (2/2 OCC, 7 state machines, 7 calculations, 39 error IDs surfaced), path-purity PASS (0 path tokens in §3). Confirmed neither design file was read. §2.2 verified byte-identical to canonical block.

## Step 5: Generate Unit Tests — 2026-06-22T12:13:00.000Z

**Stage 1 — `test_helpers/`** (9 files): `types.py` (SkinExamPhoto append-only id+created_at only), `api_client.py` (one method per endpoint), `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (5 roles; `make_provider_headers()` since Provider is the lone entity_backed role), `fixtures.py`, `__init__.py`. Imports cleanly.

**Stage 2 — `test_suite/`**: `conftest.py` + 7 domain test files, **66 test functions total**.

**Coverage**: Queue A (Difficulty) 35 tests across 17 of 18 instances (≥2 each); Queue B (Corner) 31 tests across all 31 non-stub instances (≥1 each). All 5 `excluded_because` stubs cross-reference real difficulty instances, correctly left untranslated.

**Skipped instances: 1** — `Difficulty/priority_pair_validation_conflict/pa_not_approved_beats_billing_lock_on_biologic_charge` fails unique derivability: asserts `ERR_PA_NOT_APPROVED` (P12) pre-empts `ERR_ENCOUNTER_BILLING_LOCKED` (P14, also 409); PRD §2.8 fixes order only through the 409-state stage then lumps business checks without stated relative ordering. Two faithful implementers could resolve either way.

**Audits passed**: every docstring ends with one verbatim `Design:` tag; all 83 PRD citation quotes confirmed verbatim; no skip/skipif/xfail; no scaffold leakage; all files byte-compile; pytest collects all 66.

## Step 6: Generate Implementation — 2026-06-22T12:13:30.000Z

Generated Python + Flask in-memory implementation in `workspace/implementation/` (23 source files): `start.sh`, `requirements.txt` (flask==3.0.3), `app.py`, `clock.py` (default `2026-01-01T00:00:00Z`), `db.py`, `errors.py`, `response.py`, `middleware.py`, `helpers.py`, `services.py`, `routes/` (13 blueprint modules). **60 routes** (matches PRD §4).

**Contract confirmation**: start.sh reads `$PORT` (default 10000), binds `0.0.0.0`, runs foreground via `exec python3 app.py`, guards pip install. Storage in-memory dicts only — no SQLite/JSON/tmp. `db.reset()`+`clock.reset()` at app creation. Zero seeded entities.

**Self-verification**: ran 56 live assertions across three suites (all passing). **Noted gap**: `SkinExamPhoto` has no catalogued not-found error ID; GET-by-id miss returns 404 `ERR_PHOTO_NOT_FOUND`. Implementer mentioned "35 IDs from PRD §5" vs PRD's 39 surfaced — to verify in Step 7.

## Step 7: Run Tests and Iterate — 2026-06-22T12:30:00.000Z

**Iterations run:** 2 (initial diagnostic sweep + one fix-and-verify sweep). Final: all 8 parallel rounds green, **66/66 passing in every round**, no flakiness. The initial 8-round sweep was perfectly deterministic — the same 3 tests failed in all 8 rounds. All three were **test-side bugs** (STEP 2); the PRD-faithful implementation was correct and was not weakened.

**Tests deleted:** none. (No test failed STEP 1 coverage/unique-derivability outright; partial-coverage timestamp cases handled by STEP 1c — keep the PRD-covered value assertion, drop the PRD-unspecified format part.)

**Fixes applied to `test_helpers/`:**
- `test_helpers/assertions.py` — added `_parse_instant()` + `assert_same_instant()`. PRD pins three-fractional-digit serialization only for `created_at`/`updated_at`/`api_request_timestamp` (§2.2, §2.4); it does NOT pin a serialization for clock-derived domain timestamps (`due_at`, `last_skin_check_at`). Impl emits `...00:00:00.000Z`; a faithful implementer could equally echo the clock value verbatim (`...00:00:00Z`). New helper compares by instant, preserving the PRD-covered value (12-months-out / clock-now) while dropping the PRD-unspecified format.

**Fixes applied to `test_suite/`:**
- `test_05_scheduling_and_overlap.py::test_room_touching_endpoints_zero_buffer_allowed` — fixture re-used the same provider for the second booking whose start exactly equaled the first's end. PRD §3.4 makes the provider interval closed, so impl correctly returned `ERR_PROVIDER_DOUBLE_BOOKED`, masking the room half-open touching-endpoint rule under test. Fixed by booking the second interval with a distinct provider.
- `test_06_entities_and_lifecycle.py::test_skincheck_close_...` — relaxed exact-string equality on `last_skin_check_at`/`due_at` to `assert_same_instant(...)`; added import.
- `test_07_corner_calculations_validations.py::test_biopsy_recall_horizon_benign_twelve_months` — relaxed exact-string equality on `due_at` to `assert_same_instant(...)`; added import.

**Fixes applied to `implementation/`:** none. Implementation was PRD-faithful on all three counts (provider closed-interval double-booking; `.000Z` is a valid ISO-8601 three-fractional-digit form).

**Orchestrator notes verified:** `ERR_PHOTO_NOT_FOUND` for SkinExamPhoto GET-by-id miss does not trace to PRD's catalogue, but no test exercises it — left as-is (out of scope, not asserted). The skipped difficulty instance was correctly not translated. All 39 PRD error IDs present in impl's error catalogue.

## Step 8: Finalize PRD — 2026-06-22T12:25:00.000Z

Produced `workspace/PRD_FINALIZED.md`. Line counts: PRD.md 324 → PRD_FINALIZED.md 326 (+2 lines, +0.62%). One paragraph inserted, no deletions.

**Change log:**
- **§2.4 — insert** — pinned serialization format of clock-derived/echoed domain timestamps (`due_at`, `last_skin_check_at`, `scheduled_at`, `start_at`, `end_at`) to the three-fractional-digit `...Z` form (e.g. `2026-01-01T00:00:00.000Z`), matching system fields — `implementation/db.py:53-55` (`iso()`) via `services.py:49`, `routes/encounters.py:48,118`, `routes/procedure_bookings.py:80-81`, `routes/recall_reminders.py:27`.

**Pre-edit search (Edit 1):** Subject = serialization format of every server-emitted timestamp string. Enumerated all `db.iso`/`.iso(` callsites — single serializer `db.iso(dt)` emits three fractional digits + `Z` for ALL timestamps (created_at/updated_at, api_request_timestamp, due_at, last_skin_check_at, scheduled_at, start_at, end_at). Widened wording from Step 7's two fields to a global "every timestamp-valued field the server emits" rule to avoid falsely implying other domain timestamps differ. Verified clock-set returns empty `{}` and sweep compares by parsed instant.

**No PRD edit (verified):** test_05 provider closed-interval double-booking was a pure fixture bug — PRD §3.4 already uniquely determines both provider closed-interval and room half-open+buffer rules. The two test_suite timestamp fixes + test_helpers `assert_same_instant` all trace to the single §2.4 silence addressed by Edit 1.

## Step 9: Complete PRD — 2026-06-22T12:31:00.000Z

Produced `workspace/PRD_COMPLETED.md` (copied from `PRD_FINALIZED.md`, then patched). Line counts: 326 → 327 (+1). Char counts: 51,840 → 54,774 (+2,934). **12 changes: 10 ambiguity-pins, 2 mismatch-revisions.**

**Per-change list:**
- **2.1 RBAC** — insert — ambiguity — unrecognized `X-User-Role` → `ERR_MISSING_AUTH_CONTEXT` (401) — `middleware.py:27-30`
- **2.4** — insert — ambiguity — `version` initial value `1` on creation — `db.py:70`
- **2.8** — insert — ambiguity — `SkinExamPhoto` GET miss → `ERR_PHOTO_NOT_FOUND` (404), the one entity absent from catalogued not-found list — `routes/skin_exam_photos.py:47`
- **2.8** — insert — ambiguity — generic `ERR_INVALID_REQUEST` body validation runs before existence/state checks, except biopsy-result endpoint (state `ERR_BIOPSY_BAD_STATE` precedes `ERR_INVALID_BIOPSY_RESULT`) — `routes/biopsies.py:80-85`
- **3.1 Providers** — revise — mismatch — `npi` uniqueness NOT enforced; duplicates accepted (PRD claimed "unique") — `routes/providers.py:14-28`
- **3.1 Providers** — insert — ambiguity — inactive-provider encounter create → `ERR_INVALID_REQUEST`; booking does not re-check activeness — `routes/encounters.py:32-33`
- **3.1 Rooms** — insert — ambiguity — `turnover_buffer_minutes` non-negative else `ERR_INVALID_REQUEST` — `routes/rooms.py:21-22`
- **3.2 Patient** — insert — ambiguity — coinsurance inclusive 0–1, deductible non-negative — `routes/patients.py:20-24`
- **3.6 Membership** — insert — ambiguity — `purchased_unit_cents` non-negative — `routes/cosmetic_memberships.py:23-24`
- **3.7 Charges** — insert — ambiguity — charge-guard order: biologic-PA gate → billing-lock → allowed-amount — `routes/charges.py:43-68`
- **3.7 Charges** — insert — ambiguity — allowed-amount does not gate BIOLOGIC charges (self-priced; client `insurer_allowed_cents` ignored; CASH biologic forces null) — `routes/charges.py:52-68`
- **3.9 Prior Auth** — insert — ambiguity — `decision` exactly `APPROVE`/`DENY`; `required_step_count` non-negative — `routes/prior_authorizations.py:14,25-26`
- **3.10 Recall sweep** — insert — ambiguity — returns array-typed list, swept reminders ordered `created_at` ASC, `limit`/`total_count`=swept count, `offset` 0 — `routes/system.py:34-43`
- **Section 5** — insert — ambiguity — added `ERR_PHOTO_NOT_FOUND` (404) catalogue row — `routes/skin_exam_photos.py:47`

## Pipeline Complete — 2026-06-22T12:31:30.000Z

**Final state: all 8 parallel stability rounds PASS 66/66.** Task `task_0623_dermatology_practice` (Dermatology Practice, Expert band) complete. Artifacts: SCAFFOLD.yaml + 2 design files, worklog.md, test_helpers/, test_suite/ (66 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}.
