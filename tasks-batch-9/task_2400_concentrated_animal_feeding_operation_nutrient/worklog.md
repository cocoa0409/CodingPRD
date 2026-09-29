# Worklog — task_2400_concentrated_animal_feeding_operation_nutrient

## Step 1: Create task directory — 2026-09-02T07:22:03.260Z

Created `tasks/task_2400_concentrated_animal_feeding_operation_nutrient/` and `tasks/task_2400_concentrated_animal_feeding_operation_nutrient/workspace/` (pre-allocated directory name used verbatim; no index scan).

## Step 2: Generate scaffold — 2026-09-02T09:27:01.716Z

All three artifacts for task 2400 are complete and pass the scaffold linter.

## Deliverables (all in `/home/ubuntu/github/CodingPRD/tasks/task_2400_concentrated_animal_feeding_operation_nutrient/`)

- `SCAFFOLD.yaml` (3,070 lines) — §1.0–§1.7 only: 14 entities, 8 state machines, 1 OCC rule (`plan-create-stale-operation` → `ERR_STALE_OPERATION_VERSION` 412), 12 calculations, 46 ordered validations, 73 endpoints, 58 errors, 5 roles. Contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1,923 lines) — single key `scaffold_difficulty_design`: 9 rules × 22 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` (4,257 lines) — single key `scaffold_corner_design`: all nine guide sections, 69 instances (51 full recipes + 18 `excluded_because` stubs).

## Work finished this session
Appended the last four §1.9 sections:
- **errors** — real trigger for the previously unreachable `ERR_BUDGET_NOT_ACTIVE` (a budget filed on an already-APPROVED plan is born LOCKED, so the event passes priority 19 and fails priority 20 with 409), plus four stubs deferring to §1.8 for the coverage/hauler-license errors.
- **rbac** — priority-ordered 401/403 gates (`ERR_UNAUTHENTICATED` outranks `ERR_UNAUTHORIZED` outranks `ERR_OWNERSHIP_VIOLATION`, probing both entity-backed identities), a positive matrix instance exercising one exclusive operation of each of the five roles end-to-end, and `ERR_SEGREGATION_OF_DUTIES` on **both** declared paths into `CLOSED`.
- **cross_cutting_complexity_layers** — the mandatory OCC instance (stale `expected_operation_version` → 412; retry with the observed version succeeds; the successful plan create itself bumps `Operation.version`, so the token can't be replayed) and a `rate_threshold_triggers` instance pinning three boundaries on one measurement (deficit exactly at `required_freeboard_in` → no alert; `measured_freeboard_in == 6` → `OVERFLOW_IMMINENT`, not `FREEBOARD_ALERT`; non-NORMAL visual raises `alert_raised` without meeting the alert transition's deficit precondition, yet still blocks return-to-service), plus stubs for the cascade and dual-variant layers.
- **consistency_model** — one `immediate` instance proving a single application event's four-entity fan-out is visible in its own response and the next reads.

One `SCAFFOLD.yaml` edit was needed: the `POST /cafo/field-budgets` side effect said budgets are `LOCKED "until the plan is approved"`, which was ambiguous for a plan that is *already* APPROVED. It now states explicitly that a budget is always born LOCKED and only `POST /cafo/nutrient-plans/{id}/approve` activates budgets — which is what makes the `ERR_BUDGET_NOT_ACTIVE` claim deterministic.

## Verification
- `scaffold_lint.py` → `VERDICT: clean lint` (872 calls scanned across §1.8+§1.9; 73 endpoints, 14 entities; all FKs reverse-reachable).
- All three files parse as YAML with the required top-level key shapes.
- 91 instance names, zero duplicates across both design files; every stub has `claim_type` + `grounds` + `excluded_because` with no `test_recipe`, and every cited `difficulty_instance` resolves by bare name in §1.8.
- All 58 error codes are asserted as an actual returned `error_id` somewhere in §1.8/§1.9 (the seven that don't use `== ERR_X` phrasing use "are each ERR_X" in multi-arm asserts).
- Placeholder-closure replay across both files: every `${var}` used in a `call`, `payload`, `as_user_id` or `assert` is captured by an earlier call in the same instance — 0 problems.
- Section names and `claim_type` values are drawn only from `references/claim-extraction-guide.md`'s nine sections and their per-section rows.
- The hard constraint was honored: no sibling `tasks/task_*/` directory was listed, read, or grepped.

## Step 3: Copy shared files — 2026-09-02T09:27:01.716Z

Copied `INSTRUCTION.md` → `tasks/task_2400_concentrated_animal_feeding_operation_nutrient/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T09:43:12.494Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2400_concentrated_animal_feeding_operation_nutrient/workspace/PRD.md` (536 lines) from `SCAFFOLD.yaml` alone.

**Structure** (deliberately not the example's shape):
- §1 Introduction — 3 paragraphs, regulatory/enforcement framing
- §2 — 10 domain-derived subsections: RBAC, response structure (verbatim), pagination, record identity & immutable registers, the logical clock, measurement precision & rounding discipline, validation order, optimistic concurrency on the operation record, compliance posture as a system-wide gate, the two conserved-quantity ledgers
- §3 — 9 workflow subsections grouped by regulatory arc (operation sizing → permit coverage → land base → plans/budgets → storage → land application → transfers → incidents/inspections/cascade → annual reporting)
- §4 — 73-row, 4-column table; §5 — 58-row, 2-column table. Document ends at §5, no footer.

**Hard Contract results (all mechanically verified, two independent passes):**
- **Contract 1 — Field-Name Coverage: PASS.** Pass 1 against a pre-built 192-token set: 0 missing. Pass 2 re-derived independently from the scaffold (all `entities[].fields[].name` plus every `input`/`request_body`/`query_params`/`path_params` key, optional `?` markers stripped) — 183 tokens, 0 missing. Also verified: all 58 `errors[].id`, all 88 enum members appearing in `constraints` text, all 73 endpoint method+path pairs, and all 43 state-machine transitions (from/to state pairs) present.
- **Contract 2 — Rule Coverage: PASS.** All 46 validations appear in §2.7 in exact scaffold priority order (positional-order check: 0 inversions), each with its `error_id`, and every `applies_to` scope is reflected either in §2.7 or in the §3 narrative that names it. All 12 calculations rendered as step-by-step prose with pinned evaluation order; every numeric constant in every `calculations[].constants` block is present in the prose except `MORTALITY_PCT = 0.01`, which is rendered as "one percent of the operation's `head_count`". All 43 endpoints carrying `side_effects` have their cross-entity fan-out narrated (application-event four-entity fan-out, void compensation, transfer commit/release/re-commit asymmetry, the notice-of-violation four-hop cascade, clock-set recomputation). Sibling-branch symmetry covered on all six branch points (plan approve vs. require-revision; storage FREEBOARD_ALERT vs. OVERFLOW_IMMINENT; event verify vs. void; transfer cancel-from-INITIATED vs. cancel-from-SUSPENDED; incident close-from-OPEN vs. close-from-WRITTEN_SUBMITTED; inspection close-from-CONDUCTED vs. close-from-RESPONSE_SUBMITTED).
- **Contract 3 — §3 Path Purity: PASS.** 356 distinct backtick tokens in §3; zero start with `/`, zero are bare HTTP methods, zero combine method+path, zero contain `/cafo`. Zero raw (un-backticked) path or HTTP-method mentions in §3 either.

**Additional verification:** §2.2 matches `section-2.2-response-structure.md` byte-for-byte. Zero fuzzy words. Zero pseudocode operators outside code fences. The §4 intro's 201-for-create / 200-for-everything-else claim was checked against all 73 endpoints' `code` values: exact match, 0 exceptions.

**Constraint honored:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

## Step 5: Generate unit tests — 2026-09-02T10:32:07.315Z

All work is complete. Final state of `/home/ubuntu/github/CodingPRD/tasks/task_2400_concentrated_animal_feeding_operation_nutrient/`:

## What was generated

**`test_helpers/`** (Stage 1, 8 modules): `api_client.py` (all 73 endpoints), `api_errors.py` (58 error ids + HTTP status map), `types.py`, `constants.py`, `factories.py` (canonical payloads with `_OMIT` sentinel merging), `fixtures.py` (granular builders + `setup_scenario` 9-stage chain, `setup_ready_operation`, `setup_committed_transfer`, `setup_conducted_inspection`), `assertions.py` (invariant-checking helpers: `assert_budget_ledger` always re-checks applied+remaining==total, `assert_storage_balance` always re-checks both volume-balance identities), `test_users.py` (identity threading: Operator `X-User-ID` == operation id, Hauler == hauler row id).

**`test_suite/`** — 16 modules, 126 tests, every test carrying exactly one `Design:` line as its last docstring line.

| queue | files | tests | instances |
|---|---|---|---|
| A (Difficulty, §1.8) | `test_01`–`test_09` | 44 | 22 / 22, exactly 2 tests each |
| B (Corner, §1.9) | `test_10`–`test_16` | 82 | 50 / 51 non-stub; 18 `excluded_because:` stubs emitted nothing |

## Verification passes (all run programmatically)

- **Design-tag audit** — 126/126 tests carry exactly one tag, last line, correct `Difficulty/<rule_id>/<name>` or `Corner/<section>/<name>` form, every name resolves to a real instance in the right section, no stub name cited, no dual tags.
- **Coverage audit** — all 22 difficulty instances ≥2 tests; 50 of 51 non-stub corner instances ≥1 test.
- **PRD-citation pass** — every `PRD: "..."` quote (≈300) survives a literal substring match against `workspace/PRD.md`, backticks included. Four of my own quotes failed the first run and were replaced with the PRD's actual sentences.
- **Design-doc-citation pass** — zero occurrences of "scaffold" or design-document section refs anywhere in `test_suite/` or `test_helpers/`.
- **Static pass** — `py_compile` clean, `pyflakes` clean (one unused local in `test_14` removed), and an AST check confirms every `api_client.*` method and every `test_helpers` import symbol actually exists.

## The one skipped instance

`Corner/errors/budget_created_after_approval_stays_locked_and_blocks_events` — its premise is that `POST /cafo/field-budgets` has no plan-state gate. PRD §3.4 states the opposite ("may only be added by a `CertifiedPlanner` while the plan is in `DRAFT`; adding one to a plan in any other state is refused with `ERR_PLAN_STATE_INVALID`"), and plan-state legality (priority 10) precedes budget-active (priority 20), so the asserted outcome is not uniquely derivable. Dropped per the PRD-first filter; no placeholder, no xfail.

## Design-index literals overridden in favour of PRD arithmetic

Recomputed independently, kept the instance, asserted the PRD-derivable value:
- freeboard instance: index pins `available_capacity_gallons == 0.00` after an 18-inch reading, PRD arithmetic gives −224,415.00 → asserted `days_of_storage_available == 0` only, and deliberately avoided `assert_storage_balance` there.
- South 20 `required_setback_ft`: index says 200, PRD precedence gives 100.
- aggregate-ceiling rate: index says 10425.33, PRD gives 10424.81.
- NOV-then-application arm: index expects `ERR_OPERATION_RESTRICTED`, but the cascade drives the plan to `REVISION_REQUIRED` first, so `ERR_PLAN_NOT_APPROVED` (priority 19) wins — that call was dropped and the cascade state asserted directly.
- a future-dated incident payload in the index used an invalid `disposal_method` and named no subject, which would fail request-shape before the future-dated check; refiled as a `DISCHARGE` with `subject_storage_id`.
- unstated-null and echo-key claims (`notification_late` default null, nutrient-summary `year`/`basis` echoes, record `version` literals) were replaced by numerically provable equivalents.

Nothing was run against a live server — the implementation agent is still building it.

## Step 6: Generate implementation — 2026-09-02T10:32:07.315Z

Implementation complete and verified.

## Files (all under `workspace/implementation/`)

- **`core.py`** — in-memory store (starts empty, no seeding), server-held logical clock pinned to `2026-08-01T00:00:00Z`, Decimal helpers (`prec=40`, ROUND_HALF_UP / ROUND_FLOOR, no floats, no `round()`), ISO-8601 formatters, the response envelope (`meta`/`response_type`/`data`, `limit`/`offset`/`total_count`/`has_more` on lists), all 58 error ids → HTTP statuses, `ApiError`.
- **`calc.py`** — all 12 pinned calculations plus the derived-recompute engine (posture evaluation, transitive cascade, both conserved-quantity ledgers).
- **`app.py`** — Flask app: exactly **73 routes, verified 1:1 against `SCAFFOLD.yaml`'s endpoint list** (no missing, no extra), the 46 validations in scaffold priority order, RBAC/ownership/SoD gates, OCC on plan create.
- **`requirements.txt`**, **`start.sh`** (executable, `cd "$(dirname "$0")"`, guarded pip install, `exec python3 app.py`, `PORT` default 10000, binds `0.0.0.0`). Flask 3.1.3 is already present system-wide, so the install step is a no-op and re-boots are fast — important for `--isolation per-test-server`.

## Verification performed

Three replay suites, all passing:
1. Canonical-fixture chain over HTTP against a `start.sh`-launched server: 420.00 AU / MEDIUM / permit_required, 3374298.00 and 9244.65, storage 5385960.00 / 897660.00 / 4488300.00, `design_storage_days` 485, setback 200 / excluded 4.13 / net 38.37, p_index 43.68 MEDIUM, the full nine-step budget (209.00 → 10800/14000 → NITROGEN → 414396), `days_of_storage_available` 377, event n 23.45 / p2o5 15.03, late renewal 589.00 → 699.44, plus envelope/pagination and the 401/403/403 gate ordering.
2. Endpoint sweep touching every entity and both computed reads, including the pinned PATCH-repropagation corner (2700000.00, 7397.26, 606 on both the operation and the structure, `Operation.version == 2`, `ManureStorage.version == 1`). It also asserts **exact field-set equality against every one of the 14 scaffold entities**.
3. Corner replay of the on-time renewal instance (559.55, re-dated term 2031-01-01 → 2036-01-01 / 2035-07-05 / 2035-10-03), the transfer commit → suspend → release → resume → re-commit asymmetry, `close`-from-`OPEN` incidents, and the defaulted nutrient summary after a clock rollover.

## Design decisions worth flagging

- **Version semantics.** Derived recomputation writes via `set_derived` (never touches `version`/`updated_at`); only explicit mutations use `set_fields`/`touch`. This also keeps GETs write-free.
- **`available_capacity_gallons` is never clamped**; only `days_of_storage_available` and the projection's `days_of_storage` floor at 0.
- **`POST /cafo/field-budgets` accepts DRAFT *and* APPROVED plans** (born LOCKED either way); CERTIFIED/SUBMITTED/REVISION_REQUIRED/SUPERSEDED give `ERR_PLAN_STATE_INVALID` 409.
- **`complete-renewal`** enforces its declared "at least one APPROVED plan" precondition with `ERR_PLAN_NOT_APPROVED` (409).
- List filters and read-only params are accepted from either the query string or a JSON body.

## Step 7: Run tests and iterate — 2026-09-02T14:05:11.000Z

Step 7 is complete with a clean 8-round sweep. **No test or implementation changes were needed.**

## Summary

**Iterations run:** 2 sweeps (16 rounds total).

**Collection check (the orchestrator's main concern):** resolved as a non-issue. All **126** test functions on disk collect cleanly — `126 tests collected`, zero collection errors. The prior run's `total=106` was a stale tally from *before* the final edits to `test_11/14/15/16/conftest.py` (all timestamped 10:39); nothing was hiding ~20 tests. Every round of both sweeps ran the full 126.

**Tests deleted:** none. **Fixes to `test_helpers/`:** none. **Fixes to `implementation/`:** none. No failure survived STEP 0 as a real defect.

### Sweep 1 (6/8 clean) — 4 failures, all diagnosed as external infrastructure interference

| round | test | error |
|---|---|---|
| 3 | `test_frozen_ground_is_reported_before_the_remaining_allowance` | `RemoteDisconnected` |
| 5 | `test_freeboard_reading_reconciles_the_volume_balance_and_alerts_the_structure` | `RemoteDisconnected` |
| 5 | `test_unapproved_plan_rejection_writes_nothing_at_all` | `ConnectionResetError(104)` |
| 5 | `test_records_basis_ignores_initiated_transfers_and_voided_events` | `ConnectionResetError(104)` |

All four were transport-level only — zero tripped assertions, and **zero Python tracebacks in any of the 8 server logs**, so the implementation never raised or crashed.

The decisive evidence was a host-wide histogram of `Terminated` (SIGTERM) events across all **856** `/tmp/prd_bench_server_*.log` files on this machine. They occur in synchronized bursts hitting *many different tasks at once*: 25 servers SIGTERMed within the second at 13:34:25, 23 at 13:33:52, 19 at 13:38:41, 19 at 13:34:16, 14 at 13:38:31. No single round's runner can kill other tasks' servers, so this is an external host-wide `pkill`-style cleanup from a neighbouring pipeline.

I ruled out the two plausible internal causes before concluding:
- **Not sweep reaping by my own shell** — the sweep was `setsid`-detached, and per-test servers spawn with `start_new_session=True`.
- **Not the runner's own teardown** — `ensure_liveness` fired **0** times, and `lifecycle.stop()` (the only SIGTERM path in the runner) logged only 8 times, all at end-of-run teardown at 13:40:46–13:41:06. The mid-run 13:33/13:38 SIGTERMs had no corresponding runner log line at all.

The server logs show the implementation serving `201`s (`POST /cafo/soil-tests`, `POST /cafo/fields`, `POST .../intake`) in the same second it was killed — a healthy server shot from outside. I also considered and rejected a stale keep-alive-socket theory (the client is a module-level `requests.Session` with `max_retries=0` against a per-test-restarted server): if it were live, failures would scatter across the 6 clean rounds too, and none did. I deliberately made no speculative "hardening" edit to `test_helpers/api_client.py` on a disproven hypothesis.

### Sweep 2 (confirmation, unchanged artifact) — clean

| round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| passed/total | 126/126 | 126/126 | 126/126 | 126/126 | 126/126 | 126/126 | 126/126 | 126/126 |

0 failed, 0 errors, 0 skipped in every round; all results files freshly written 13:53:13–13:53:24; no runner processes left behind.

One caveat worth passing on: those external SIGTERM bursts are a property of this shared host, not of this task, so any future sweep here can show the same non-reproducible transport failures. The signature to check first is `grep -c Traceback` on the server log (0 = implementation is fine) plus the host-wide `Terminated` histogram.

Files of interest: `workspace/implementation/results.{1..8}.json`, `workspace/sweep.log`.

**Orchestrator's independent verification:** all 8 `results.{1..8}.json` re-read directly — every round `passed=126 total=126 failed=0 errors=0 skipped=0`. Confirmed CLEAN.

## Step 8: Finalize PRD — SKIPPED — 2026-09-02T14:06:40.000Z

Skipped per the skill's skip condition. Step 7 made **0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes** — the `<step_7_diff>` hand-off would be empty, so there is no PRD-silence or PRD-mismatch site for Step 8 to patch.

Orchestrator's reasoning on the one judgement call: Step 7 ran two sweeps rather than exiting on the first, so it did not literally "exit on the first 8-round sweep". But the second sweep was a pure confirmation re-run against a **byte-identical artifact** — the only reason a second sweep happened is that four transport-level failures in sweep 1 were traced to host-external SIGTERM bursts rather than to the code. Zero artifact changes were made between the sweeps. The skip condition's substance ("zero iterations beyond the baseline", `PRD.md` already determines every behavior the implementation exhibits) is therefore satisfied, and spawning Step 8 with an empty diff could only produce unmotivated PRD edits that Step 9 would have to undo. Skipping. Step 9 runs next and performs the full PRD-vs-implementation scan regardless, so no coverage is lost.

## Step 9: Complete PRD — 2026-09-02T14:11:20.000Z

Verified: all 38 edits landed cleanly (final §2.9 tie-break edit confirmed at line 198), headings identical to source (no new sections), all 135 table rows preserved. I also re-verified the one pin I was least certain of — `fk()` runs on the raw body *before* `validate()` (app.py:1067-1070), and `get()` returns `None` for a non-string id (core.py:202-205), so a wrong-typed foreign key really does surface as the target's 404 code rather than `ERR_INVALID_REQUEST`.

## Deliverable

`workspace/PRD_COMPLETED.md`

| | lines | chars |
|---|---|---|
| `PRD.md` (source) | 534 | 115,623 |
| `PRD_COMPLETED.md` | 538 | 127,774 |
| delta | **+4** | **+12,151** |

The +4 lines are two new standalone paragraphs (§2.6 input-rounding, §2.7 cross-parent FK consistency) whose pins were too multi-clause to thread into an existing sentence; every other change is an in-paragraph insert or revision.

## Counts

- **Ambiguity-pins: 30**
- **Mismatch-revisions: 8**
- Total changes: 38

## Change ledger

- §2.1 — insert — ambiguity — Hauler ownership also guards *reading* a hauler record, not just writes — app.py:606-613
- §2.3 — insert — ambiguity — `offset` must be non-negative; malformed `limit`/`offset` → `ERR_INVALID_REQUEST`; unknown query params ignored — app.py:314-332
- §2.3 — insert — ambiguity — list endpoints are never ownership-scoped; every authorised role sees all rows — app.py:354-359
- §2.4 — insert — ambiguity — domain instants omit the fractional part when milliseconds are zero, while audit stamps always carry three digits — core.py:80-93
- §2.4 — **revise** — **mismatch** — derived recomputation moves neither `updated_at` nor `version`; only explicit mutation does — calc.py:144-163, core.py:188-194
- §2.5 — insert — ambiguity — the clock may move backwards; which returned counts are "moved" vs. plain recomputed totals — app.py:2090-2125
- §2.6 — insert — ambiguity — supplied numerics are persisted quantised to 2 dp, with the three full-precision exceptions named — app.py:1090-1112, 1406-1413, 1456-1458
- §2.7 — insert — ambiguity — no cross-parent FK consistency is enforced except the budget's soil test ↔ field — app.py:1064-1088, 1827-1837
- §2.7 — insert — ambiguity — a wrong-typed foreign key is reported with its target's not-found code, not as a shape error — app.py:156-166, core.py:202-205
- §2.8 — insert — ambiguity — only two writes advance `Operation.version` — app.py:455-458, 525-526, 825
- §2.9 — insert — ambiguity — posture recompute re-runs harmlessly on unrelated writes — app.py:1200, 1466, 1570
- §2.9 — insert — ambiguity — cascade transfer ordering ties broken by insertion order — calc.py:662-671
- §2.9 — insert — ambiguity — resuming under `SUSPENDED` yields `ERR_OPERATION_RESTRICTED` — app.py:1643
- §3.1 — insert — ambiguity — stored `recorded_annual_manure_gallons` tracks the clock's year — calc.py:707-716
- §3.1 — insert — ambiguity — PATCH scope; `null` ignored; a no-op body still bumps `version` — app.py:505-527
- §3.1 — insert — ambiguity — nutrient-summary basis/year validation and echo — app.py:541-573
- §3.2 — **revise** — **mismatch** — submission does *not* require `permit_required`; un-issued coverage interval is `effective_on` + 5 y — app.py:676-699
- §3.2 — insert — ambiguity — Feb-29 calendar-year replacement; a drafted permit's null fields — core.py:96-100, app.py:644-664
- §3.2 — **revise** — **mismatch** — complete-renewal tests suspension *before* the approved-plan check; fee fields preserved — app.py:740-761
- §3.2 — **revise** — **mismatch** — two different coverage-expiry tests apply to events vs. transfers — app.py:449-452, 1390-1392
- §3.4 — insert — ambiguity — enum arrays dedupe, preserving first-appearance order — app.py:269-291
- §3.4 — **revise** — **mismatch** — budgets may be added while the plan is `DRAFT` *or* `APPROVED` — app.py:1078-1082
- §3.4 — **revise** — **mismatch** — require-revision *locks* the plan's budgets — app.py:928
- §3.4 — insert — ambiguity — revision leaves `revision_count`, `approved_at` and budgets untouched — app.py:836-851
- §3.5 — insert — ambiguity — intake `gallons` must exceed 0 and is the only accepted field — app.py:1189
- §3.5 — **revise** — **mismatch** — operation-wide `design_storage_days` takes its seasonal factor from the first seasonal structure — calc.py:396-408
- §3.5 — insert — ambiguity — capacity projection uses the addressed structure's own factor for both bases — app.py:1241-1271
- §3.5 — insert — ambiguity — latest-inspection selection ties broken by insertion order — calc.py:455-463
- §3.5 — revise — ambiguity — `last_inspected_on` is the greatest `inspected_on`, so a back-dated filing does not move it — calc.py:436-445
- §3.6 — **revise** — **mismatch** — an event's coverage test is against the plan's *own* permit — app.py:1390-1392
- §3.6 — insert — ambiguity — verify is idempotent on an already-`VERIFIED` record — app.py:1470-1481
- §3.7 — insert — ambiguity — `recipient_name`/address are mandatory non-empty at initiation — app.py:1517-1518
- §3.8 — insert — ambiguity — notification obligation is derived once; `notification_late` is born false — app.py:1736-1738
- §3.8 — insert — ambiguity — `findings_count` mandatory ≥ 0; `deficiency_categories` defaults to `[]`, dedupes, no cross-check — app.py:1862-1880
- §3.8 — insert — ambiguity — scheduled-inspection initial nulls; `scheduled_on` is not future-checked — app.py:1838-1855
- §3.9 — insert — ambiguity — `variance_explanation` non-empty when present; duplicate check spans all statuses; initial nulls — app.py:1984, 2000-2018
- §3.9 — insert — ambiguity — a rejected submit still persists the recomputed mass balance — app.py:2034-2041
- §4 — insert — ambiguity — no-body transitions reject *any* field; the storage-inspection POST returns the inspection — app.py:205-207, 1332

Note: `workspace/test_helpers/` and `workspace/test_suite/` do not exist for this task, so no test cross-reference was available (immaterial, since implementation was the sole alignment authority). The 73-route count in §4 was confirmed exact — the 77 `@app.` decorators include 4 `errorhandler`s.

**Orchestrator's correction to the Step 9 note above:** `test_helpers/` and `test_suite/` DO exist — they live at the task root (`tasks/task_2400_.../test_helpers/`, `.../test_suite/`), not under `workspace/`, so the subagent looked in the wrong place and found nothing. This is immaterial to the deliverable: the skill designates `implementation/` as the sole alignment target and explicitly demotes tests to "auxiliary cross-reference, never authority", so the missed read cannot have introduced a wrong pin — it only removed a corroborating signal. No re-run warranted.

**Orchestrator's independent verification of PRD_COMPLETED.md:** file present (127,774 bytes); `diff` of all `^#` heading lines against `PRD.md` is empty (no new sections, none renamed or dropped); table-row count identical at 135 in both files (73-row endpoint table + 58-row error table + headers intact); tail ends on the complete final error-table row, so no truncation.
