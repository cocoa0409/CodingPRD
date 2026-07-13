# Worklog — task_0818_backflow_prevention

## Step 1: Create task directory — 2026-07-10T10:26:55.592Z

Created `tasks/task_0818_backflow_prevention/` and `tasks/task_0818_backflow_prevention/workspace/`.

## Step 2: Generate scaffold — 2026-07-10T10:49:00.000Z

All checks pass. The scaffold is complete and self-consistent.

## Summary

Generated three scaffold artifacts for **task_0818_backflow_prevention** (Backflow & Cross-Connection Control) in `/home/ubuntu/github/CodingPRD/tasks/task_0818_backflow_prevention/`:

- `SCAFFOLD.yaml`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `SCAFFOLD_CORNER_DESIGN.yaml`

**Design profile:** Expert-band, compliance/audit primary archetype blended with temporal-windowing; flat entity topology (FK-linked peers, `api_prefix: "/"`); compound/posture-driven state shape; peer-roles RBAC (UtilityAdmin opaque, Tester entity-backed, PremisesOwner opaque).

**Counts:**
- 9 entities (ServiceConnection, BackflowDevice, Tester, TestAppointment, TestReport, HazardSurvey, ShutoffNotice, RepairOrder, Reminder)
- 41 endpoints (incl. a `/_clock/set_current_utc` test-driving clock defaulting to 2026-03-01T00:00:00Z)
- 8 state machines + 1 OCC concurrency rule (survey-finalize supersede on `ServiceConnection.version`)
- 7 calculations, 15 ordered validations, 30 error codes, 3 roles
- 18 difficulty instances (all 9 §0.5 rules × 2, different-domain/pair/mode differentiation satisfied)
- 27 active corner instances + 6 `excluded_because` stubs (33 total), all names unique across both design files

**Verification performed:**
- `scaffold_lint.py` → `VERDICT: clean lint` (195 calls scanned; all §1.8/§1.9 calls conform to §1.5, all 9 FKs reverse-reachable via filtered-list GETs).
- All formula-derived assert literals independently computed by code (e.g. penalty round-per-device 499.5→500×2=1000 vs sum-then-round 999; from_install 2026-03-01 vs from_last_pass 2027-02-15; risk-tier floors; grace enforcement date 2026-03-31; empty-pool rate 0.00).
- No forbidden concurrency vocabulary; OCC endpoint declares `expected_service_connection_version` input and "increments ServiceConnection.version by 1" side-effect; file-split integrity confirmed (no design keys leaked into SCAFFOLD.yaml).

Per the hard constraint, no sibling `task_*/` directory was read — the scaffold was derived solely from the scenario text and the skill specification.

Orchestrator verification: all three files `yaml.safe_load` cleanly (1381 / 1079 / 1200 lines).

## Step 3: Copy shared files — 2026-07-10T10:51:20.706Z

Copied `INSTRUCTION.md` → `tasks/task_0818_backflow_prevention/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-10T10:58:49.886Z

The PRD is complete. All three hard contracts pass and counts reconcile with the scaffold.

**Output written:** `workspace/PRD.md`

- **PRD line count:** 262
- **Endpoints covered:** 41 (matches scaffold's 41: all CRUD + state-transition actions + `/reminders/generate`, `/utility-report`, `/_clock/set_current_utc`)
- **Errors covered:** 30 (matches scaffold's 30)

**Structure:** §1 Introduction (3 paras); §2 with 10 subsections (2.1 RBAC with all three role identities translated — `UtilityAdmin`/`PremisesOwner` opaque, `Tester` entity-backed; 2.2 verbatim envelope; 2.3 pagination; 2.4 common properties/versioning; 2.5 logical clock; 2.6 the derived `compliance_posture` cascade formula; 2.7 reachability/left-to-right existence; 2.8 precision & round-per-device-then-sum; 2.9 OCC; 2.10 the 15-step validation precedence ladder); §3 with 7 domain-lifecycle subsections; §4 4-column endpoint table; §5 2-column error table.

**Hard contract reports:**
```
Contract 1 (Field-Name Coverage): 59 required, 59 present, 0 missing — Status: PASS
Contract 2 (Rule Coverage): all 7 calculations, all 9 state machines' transitions/preconditions/side-effects,
  the OCC rule (write_endpoint=finalize + expected_service_connection_version + ERR_STALE_VERSION/412),
  the 15-priority validation ordering, cross-entity FAIL/REPAIR/REPLACEMENT cascades, and sibling branches
  (accept PASS vs FAIL, REPAIR vs REPLACEMENT, RP/DC/DCDA/PVB result, risk-tier base/floor) expressed — Status: PASS
Contract 3 (§3 Path Purity): 328 backtick tokens scanned, 0 path/method/method+path violations — Status: PASS
```

**Scaffold gaps found:** None blocking. Every constant used in a `calculations[].formula` is declared with a value (`REMINDER_LEAD_DAYS=30`, `BASE_DAILY_RATE_CENTS=333`, weight/threshold constants, grace-day and psid thresholds). One minor observation: `PREMISES_BUFFER_MINUTES` (value 60) is referenced only in the `validations` table with its value given inline (60) rather than in a `constants:` block — it is not used in any calculation formula, so this is not an undeclared-constant gap; I embedded the "60 minutes" value directly in §3.2 prose.

Orchestrator verification: §4 endpoint table has 43 rows (41 endpoints + header + separator) == scaffold's 41 endpoints.

## Step 5: Generate unit tests — 2026-07-10T11:14:00.000Z

All checks pass. The test infrastructure and suite are complete.

### Stage 1 — `test_helpers/` (9 files)
- **types.py** — 17 status/enum classes + TypedDicts for all 9 entities (all `common_fields: true`, so all carry `id/created_at/updated_at/version`).
- **api_client.py** — `ApiClient(GenericApiClient)` with one method per endpoint (incl. `set_clock` for the logical clock).
- **api_errors.py** — `ApiErrorId` enum for all 30 error IDs + HTTP status map registered with the framework.
- **assertions.py** — per-entity structural assertions.
- **factories.py** — payload factories (input fields only).
- **constants.py** — thresholds (psid, penalty rate 333c, grace days, weights/floors, 60-min buffer, 30-day lead).
- **test_users.py** — role headers. Only `Tester` is `entity_backed`, so `make_tester_headers(tester_id)` threads real IDs for ownership-gated writes; `UtilityAdmin`/`PremisesOwner` are `opaque`. `NO_AUTH_HEADERS` for the 401 case.
- **fixtures.py** — composite helpers (unique-ID creators, `setup_device_needs_repair` for the FAIL-accept cascade state, `setup_shutoff_connection`, `create_and_finalize_survey` with live-version OCC, `book_appointment`).
- **__init__.py** — barrel export.

### Stage 2 — `test_suite/` (conftest + 10 files, 63 tests)
Organized by domain concern (registration/reads, calcs, penalties/reporting, report lifecycle, cascades, notices/shutoff, scheduling, certification, validation precedence, concurrency/RBAC).

### Verification (all green)
- **Coverage**: all 18 difficulty instances have exactly 2 tests each (36); all 27 non-stub corner instances have ≥1 test (27). Total 63.
- **Stubs**: all 6 `excluded_because` error stubs correctly skipped (their difficulty owner asserts the path).
- **Tags**: no orphan/dual/untagged tests; every docstring ends with one verbatim `Design:` line resolving to a real instance.
- **Citations**: all 63 tests' quoted PRD sentences verified verbatim-present in PRD.md (whitespace-normalized).
- **Hygiene**: no scaffold/`§1.x`/Table leakage in emitted code; no `skip`/`xfail`; all files compile; suite collects cleanly.

All difficulty and corner instances passed the PRD-first two-condition filter (verbatim coverage + unique derivability), so nothing was skipped for gaps. For the two `priority_pair` and two `cross_entity_state_dependency` instances, the second test is a control that removes the higher-priority violation to prove the precedence, keeping both tests tagged to the same instance.

**Orchestrator note (process deviation):** Steps 5 and 6 were launched sequentially rather than concurrently in a single message, so `test_suite/` existed on disk before Step 6 started. The physical-isolation guarantee was replaced by an explicit hard prohibition in Step 6's prompt against reading `test_helpers/`, `test_suite/`, and both `SCAFFOLD_*_DESIGN.yaml` files. Step 6 reported it never opened them.

## Step 6: Generate implementation — 2026-07-10T11:34:00.000Z

All flows verified. Cleaning up done. Implementation complete.

Built a complete Python + Flask implementation in `workspace/implementation/`, derived solely from `PRD.md`, `SCAFFOLD.yaml`, and `INSTRUCTION.md`. The test_helpers/, test_suite/, and *_DESIGN.yaml files were never opened.

**Files written (17 Python modules + config):**
- `app.py` — Flask app factory, blueprint registration, ApiError/404/405/500 handlers
- `store.py` — in-memory dicts + logical clock (default `2026-03-01T00:00:00Z`), no seeding
- `util.py` — datetime parse/format (ISO-8601, 3 fractional digits), `add_months` w/ day clamping, Decimal ROUND_HALF_UP helpers, response envelope (`meta`/`response_type`/`data`), pagination
- `validate.py` — typed body-field validation (ERR_VALIDATION / ERR_INVALID_TIME_RANGE)
- `auth.py` — `X-User-ID`/`X-User-Role` authn, role authz
- `lookups.py` — entity-specific 404 resolution + PremisesOwner/Tester ownership scoping
- `services.py` — connection recompute (posture cascade, penalty, counts), version-bump bookkeeping, calculations (risk tiers, test result, grace days), cascade helpers
- `routes/` — connections, devices, testers, appointments, reports, surveys, notices, repairs, misc (reminders/utility-report/clock)
- `requirements.txt`, `start.sh` (guarded `pip install`, `exec python3 app.py`, `0.0.0.0:$PORT`)

**Registered route count: 41** (excluding static) — exactly matches the scaffold.

**Boot verification:** `bash start.sh` boots cleanly and answers requests. AST-parse passes on all 17 files.

**Behavior verified end-to-end against a live server:**
- Response envelope, auth (401/403), all entity CRUD, pagination (limit 1–100, has_more)
- Penalty accrual: 333¢ × 31 days × 1.0 = 10323 (per-device round-then-sum)
- FAIL cascade: device→NEEDS_REPAIR, posture→NON_COMPLIANT, auto-issued FAILED_TEST notice, connection version = 4 (create + device + auto-recompute bump + explicit FAIL increment, per PRD §2.4's additive rule)
- Repair completion auto-rescinds notice, restores posture; replacement conserves protected_device_count
- Survey finalize with OCC (stale→412), risk-tier calc w/ conditional floors, prior-survey supersede
- Shutoff enforce→SHUTOFF/water off, remove blocked (ERR_CONNECTION_SHUTOFF), restore→COMPLIANT
- Appointment double-book (half-open), 60-min premises buffer (adjacency rejected), invalid time range, tester ownership
- Test-result thresholds (RP/DC/DCDA/PVB, inclusive `>=`), clock-driven tester expiry, utility report compliance rate

**Notable interpretation decisions** (PRD-faithful, flagged since untestable-by-me): read-time connection recompute bumps `version` only on actual change (idempotent, so OCC stays predictable); `total_penalty_cents` included in the derived set; two error cases lacking a catalog entry use best-effort IDs — tester suspend/reinstate wrong-state (`ERR_TESTER_INVALID_STATE`, 409) and reminder-not-found (`ERR_REMINDER_NOT_FOUND`, 404); `relief_valve_differential_psid` required only for RP devices, `check_valve_1_psid` always required, `check_valve_2_psid` optional.

Orchestrator verification: 41 registered routes == scaffold's 41 endpoints; `app.py` present; no SQLite/JSON-dump/`/tmp` persistence; no seed/preload functions.

## Step 7: Run tests and iterate — 2026-07-10T11:37:00.000Z

All 8 rounds passed cleanly (63/63 each round, 0 failing tests in the union). No diagnostic work was needed.

Summary:
- Iterations run: 1 (the initial sweep already passed all 8 rounds).
- Tests deleted: none.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `test_suite/`: none.
- Fixes applied to `implementation/`: none.

The task is already in a clean, fully-passing state. All 8 stability rounds reported passed==total==63 with an empty union of failing tests, so there was no flakiness to chase and no PRD-coverage/consistency adjudication required.

**Orchestrator independent verification** (not taken on the subagent's word): all 8 `results.N.json` present, each `passed=63 failed=0 total=63`; union of failures across rounds = 0; `test_suite/` contains exactly 63 `def test_` functions (so `total=63` reflects the whole suite, nothing deselected); zero `pytest.mark.skip` / `xfail` markers in `test_suite/` or `test_helpers/`. Sweep was run as two waves of four concurrent rounds to avoid this host's known 8-way self-saturation false-ERROR mode.

## Step 8: Finalize PRD — SKIPPED — 2026-07-10T11:38:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the tests exercised. No `PRD_FINALIZED.md` produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-07-10T11:43:02.131Z

- **Source vs completed**: PRD.md = 262 lines / 40,114 chars → PRD_COMPLETED.md = 264 lines / 41,344 chars (+1,230 chars, +2 lines from the two new error-catalogue rows).
- **Counts**: 5 ambiguity-pins, 1 mismatch-revision (7 Edit calls total; 2 were the catalogue-row additions supporting pins).

Walked every endpoint, cascade, calculation, and error path in `implementation/` against the PRD. The overwhelming majority of impl behavior was already uniquely pinned (posture cascade, penalty rounding/order, risk-tier formula, OCC, ownership/auth ladder, due-date month arithmetic, double-book/buffer half-open logic, PASS/FAIL thresholds, auto-issue/auto-rescind cascades, version-increment side effects, list ordering/pagination, response envelopes). The gaps found and fixed:

### Changes
- **§2.6 — insert — ambiguity** — pinned `total_penalty_cents` as the unnamed "fourth derived quantity" recomputed with the counts/posture, and that a penalty-only change at read time still bumps `version` — `services.py:50-55` (`_snapshot` includes penalty), `services.py:74-95`, `services.py:111-115` (`read_recompute`).
- **§2.7 — insert — ambiguity** — added `ERR_REMINDER_NOT_FOUND` (404) to the not-found enumeration for an unresolvable reminder path id (PRD listed 8 not-found errors, omitting reminder) — `lookups.py:47-52`.
- **§3.1 — revise — ambiguity** — pinned that suspend requires `ACTIVE` and reinstate requires `SUSPENDED`, wrong-state → `ERR_TESTER_INVALID_STATE` (409); expired-window reinstate → `ERR_TESTER_NOT_CERTIFIED` (422) — `routes/testers.py:66-85`.
- **§3.6 — insert — ambiguity** — pinned that a restore against a connection that is in `SHUTOFF` but not fully cured also returns `ERR_NOT_SHUTOFF` (no distinct cure-blocked error) — `routes/connections.py:91-96`.
- **§3.7 — revise — mismatch** — PRD said the reminder batch creates a reminder for *each* `ACTIVE`/`NEEDS_REPAIR` device; impl only creates one when `days_until_due <= 30` (overdue or within the 30-day window) and skips devices more than 30 days from due. Revised prose to match — `routes/misc.py:27-49` (the `days > REMINDER_LEAD_DAYS: continue` skip).
- **§5 — insert — ambiguity** — added catalogue rows `ERR_REMINDER_NOT_FOUND` (404) and `ERR_TESTER_INVALID_STATE` (409), the two impl error ids absent from the original 30-error catalogue.

### Notably verified as already-correct (no change)
- `relief_valve_differential_psid` required only for `RP`, `check_valve_1_psid` always required, `check_valve_2_psid` optional — `routes/reports.py:42-47` matches §3.3 prose.
- Read-time recompute bumps `version` only on actual snapshot change — `services.py:103-108` matches §2.4/§2.6.
- REPLACEMENT completion has no dedicated `version` increment (only REPAIR/finalize/fail do) — `routes/repairs.py:126` vs `:134` — matches the PRD's deliberate asymmetry.

The framework-only ids `ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED`/`ERR_INTERNAL` (`app.py:32-45`) fire only for unrouted paths/unexpected exceptions, are not part of any specified endpoint's contract, and were intentionally left out of the catalogue.

**Orchestrator independent verification**: `PRD_COMPLETED.md` = 264 lines; `diff PRD.md PRD_COMPLETED.md` = 12 changed lines (minimal patch confirmed). The §3.7 mismatch claim was checked against source: `implementation/routes/misc.py:33` contains `if days > svc.REMINDER_LEAD_DAYS: continue`, so the impl does skip devices outside the 30-day window and the PRD prose was genuinely wrong. Both new error ids (`ERR_REMINDER_NOT_FOUND`, `ERR_TESTER_INVALID_STATE`) are present in `implementation/`.

---

## Pipeline complete

All 9 steps done (Step 8 legitimately skipped). Final state: 63/63 tests passing across 8 stability rounds under `--isolation per-test-server`.
