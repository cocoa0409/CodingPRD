# Worklog — task_2112_state_assessment_administration

## Step 1: Create task directory — 2026-08-17T03:11:41.489Z

Created `./tasks/task_2112_state_assessment_administration/` and `./tasks/task_2112_state_assessment_administration/workspace/`. Index 2112 chosen (highest existing was 2111).

## Step 3: Copy shared files — 2026-08-17T03:12:10.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2112_state_assessment_administration/workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate scaffold — 2026-08-17T04:09:24.735Z

Generated all three scaffold artifacts, working only from the scenario text plus the scaffold-generator skill spec (no sibling task was read).

## Files

- `SCAFFOLD.yaml` (§1.0–§1.7, 3140 lines)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`, 2023 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`, 3606 lines)

## Counts

| Table | Count |
|---|---|
| §1.1 entities | **11** (District, School, TestWindow, Proctor, SecurityAffidavit, Session, Registration, MaterialLot, CustodyEvent, IrregularityReport, ScoreAppeal) |
| §1.2 state machines | **9** (58 transitions); Registration carries 3 parallel dimensions on one row |
| §1.2.1 concurrency rules | **2** (OCC on `Proctor.version` and `Session.version`) |
| §1.3 calculations | **8** |
| §1.4 validations | **27** (priority-ordered) |
| §1.5 endpoints | **45** (incl. `POST /_clock/set_current_utc`, default clock `2026-08-01T00:00:00Z`) |
| §1.6 errors | **40** |
| §1.7 roles | **4** (segregation-of-duties model) |
| §1.8 difficulty instances | **18** (9 rules × 2) |
| §1.9 corner instances | **58** across 9 guide sections — 47 with full recipes, 11 `excluded_because` stubs |

## Design shape (deliberately above the Expert band)

Archetype **compliance/audit** × **temporal windowing**; **graph** topology with two self-referential FKs (`CustodyEvent.previous_event_id`, `Registration.makeup_of_registration_id`); **cyclic** state shape; `api_prefix: ""` (flat top-level collections).

Key difficulty mechanics: dual-variant participation rate (provisional 66.7 vs final 25.0 on identical rows) and dual-variant lot ledger (chain replay 10 vs declared 7); mode-(a) nested `min/ceil/max` seat-pressure formula, mode-(b) round-per-lot-then-sum charge (9376, not 9375), mode-(c) waiver tier keyed on gross (16250, not 18282); depth-5 breach cascade (report → affidavit → proctor → sessions → registrations) and depth-3 lot-discrepancy cascade; two priority conflicts in distinct category pairs (state vs business_constraint, business_safety vs business_temporal); two overlap rules with different interval geometry (room = half-open + 15-min buffer; proctor = closed, no buffer); conservation invariants on booklet counts and on the district charge ledger.

## Verification

All formula-derived assertions were computed in Python before being written as literals. Custom checks passed with 0 problems: placeholder closure across 850 calls, name uniqueness across both design files, grounds resolvability, `excluded_because` targets, OCC-literal ban, error-catalog coverage, enum-value closure, and the forbidden-concurrency-vocabulary ban.

Lint verdict: clean — 45 endpoints, 11 entities, 18 §1.8 instances, 47 §1.9 instances, 850 calls scanned; all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.

## Step 4: Generate PRD — 2026-08-17T04:23:12.647Z

PRD generation complete and fully verified.

## Output

`workspace/PRD.md` — **433 lines**, 91,178 bytes. Ends at §5 with no audit footer. The two withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

## Section list

1. Introduction (3 paragraphs)
2. Global Specifications — 2.1 Principals, Roles, and Operational Scope · 2.2 API Response Structure (verbatim) · 2.3 Pagination and List Ordering · 2.4 Common Resource Properties and the Custody Log Exception · 2.5 The Logical Assessment Clock · 2.6 Path Resolution and Not-Found Semantics · 2.7 The Order in Which a Request Is Screened · 2.8 Version Pinning on Proctor and Session Writes · 2.9 Counting, Rounding, and Charge Precision · 2.10 Cascades, Recomputation, and Hierarchical Consistency · 2.11 Segregation of Duties as a Standing Principle
3. Business Logic — 3.1 Program Skeleton · 3.2 Laying Out a Test Window · 3.3 Scheduling Sessions and Assigning Proctors · 3.4 Registering Students, Coding Accommodations, and Seat Pressure · 3.5 Secure Materials and the Unbroken Chain of Custody · 3.6 Test Day · 3.7 Irregularities, Breaches, and Adjudication · 3.8 Make-up Testing, Participation, and Scoring · 3.9 Release, Appeals, Finalization, and Getting Results to Families
4. Endpoint Definitions (4-column table)
5. Error Code Catalogue (2-column table)

## Per-table coverage (scaffold vs PRD)

| Table | Scaffold | PRD | Missing |
|---|---|---|---|
| §1.1 entities | 11 | 11 | 0 |
| §1.1 entity field names | 113 | 113 | 0 |
| §1.5 request-body identifiers | 59 | 59 | 0 |
| §1.5 query params | 22 | 22 | 0 |
| §1.5 path params | 11 | 11 | 0 |
| §1.2 state machines | 9 | 9 | 0 |
| §1.2 transitions | 58 (54 unique from→to) | all 54 unique pairs rendered as explicit `FROM → TO` arrows; both duplicate groups covered separately | 0 |
| §1.2.1 concurrency rules | 2 | 2 (endpoint + occ field + error id + 412 all named) | 0 |
| §1.3 calculations | 8 | 8 (incl. both dual-variant pairs) | 0 |
| §1.4 validations | 27 | 27, in explicit priority order in §2.7 | 0 |
| §1.5 endpoints | 45 | 45 rows | 0 |
| §1.6 errors | 40 | 40 rows; all 40 also mentioned in §2/§3 narrative | 0 |
| §1.7 roles | 4 | 4, each with `identity:` translated to prose | 0 |
| enum/state values | 92 | 92 | 0 |

## Hard Contracts

Field coverage check: 113/113 entity fields, 59/59 request-body ids, 22/22 query params, 11/11 path params — PASS.
Rule coverage check: 27/27 validations in priority order (§2.7), 2/2 OCC rejections, 58/58 transitions, 8/8 calculations, 45/45 endpoint side_effects, 113/113 entity fields reconstructible, 6/6 sibling-branch symmetry groups equal-density — PASS.
Path purity check (§3 only): 839 backtick tokens scanned, 0 starting with `/`, 0 bare HTTP-method tokens, 0 method+path tokens — PASS.

Additional checks: §2.2 matches the canonical block byte-for-byte; no pseudocode operators anywhere in prose; no fuzzy/approximating words; §2.8 contains no forbidden concurrency vocabulary.

## Step 6: Generate implementation — 2026-08-17T04:52:20.846Z

Generated a complete Python + Flask implementation in `workspace/implementation/`.

**Files written** (3,445 lines total):

| Lines | File | Role |
|---|---|---|
| 13 | `start.sh` | Guarded-install foreground launcher (`exec python3 app.py`, `0.0.0.0:$PORT`, default 10000) |
| 1 | `requirements.txt` | `Flask>=3.0.0` |
| 71 | `app.py` | App factory, error handlers, per-request serialization lock |
| 110 | `db.py` | In-memory dict store + logical clock + `create`/`touch` common-field management |
| 100 | `errors.py` | 40-entry error catalogue with HTTP statuses |
| 90 | `response.py` | `meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more` pagination |
| 156 | `middleware.py` | `X-User-ID`/`X-User-Role` auth, RBAC, sub-operation guards, scope helpers |
| 154 | `validators.py` | Body well-formedness (all → `ERR_INVALID_REQUEST`) |
| 380 | `derive.py` | Calculations: certification decay, seat pressure, chain replay, charge ledger, waiver bands, participation variants |
| 244 | `serialize.py` | Per-entity field projections (custody events omit `updated_at`/`version`) |
| 71 | `cascades.py` | Session cancel, session invalidation, 5-hop breach cascade, charge reversal |
| 60 | `timeutil.py` | ISO 8601 UTC parse/format with 3 fractional digits |
| 1,878 | `routes/*.py` (11 modules) | All endpoints |

**45 endpoints implemented** — exactly matching the PRD §4 routing table.

**Verification:** three purpose-built suites (~180 assertions) all pass — a full lifecycle walk (district → finalization + distribution), a calculation/cascade suite (round-then-sum ledger `4688+4688=9376`, waiver `9376−938=8438`, seat-pressure span non-linearity, breach cascade, certification expiry at exactly 365 days), and a precedence suite (segregation-of-duties before eligibility, containment before room conflict, own-status before window phase, distribution branch precedence). The server was also booted for real via `bash start.sh` and probed over HTTP, then restart-cycled 5× to mirror `--isolation per-test-server`: **ready in ~0.51 s each time with a verifiably empty store on every boot** (no seeding, no carry-over). `pyflakes` is clean.

**Two judgment calls worth flagging**, both resolved toward PRD literalism:

1. **Check ordering.** PRD §2.7's numbered list is implemented verbatim for all *numbered* checks. The un-numbered cross-aggregate preconditions that fall back to `ERR_INVALID_STATE_TRANSITION` (e.g. "a lot must exist before `PLANNED→OPEN`", "every present student scored before release") are screened *after* the numbered checks — because scaffold priority 8 scopes itself to "the target resource's **OWN** fields", and every §3 narrative orders them that way. This matters concretely: releasing a window that is short on participation *and* has unscored present students now reports `ERR_PARTICIPATION_BELOW_MINIMUM`, as §3.9 describes.
2. **Deciding an appeal on a mid-appeal-invalidated registration** succeeds (the registration, being terminal, is left untouched). The strict reading would deadlock finalization, which §3.7 explicitly says must remain reachable: "the appeal stays `FILED` and must still be decided before the window can be finalized."

## Step 5: Generate unit tests — 2026-08-17T04:56:58.218Z

Test infrastructure and suite are complete and audited.

## Files written

**`test_helpers/`** (Stage 1, 1,989 lines)
- `types.py` — 11 entity TypedDicts + 20 status enums. `CustodyEvent` correctly omits `updated_at`/`version` (PRD §2.4 append-only exception).
- `api_client.py` — 45 endpoint methods, one per PRD §4 row.
- `api_errors.py` — 40 error IDs + HTTP map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions, `assert_lot_conservation` (four-bucket sum invariant), `expected_effective_seat_capacity`, `assert_participation_precision`.
- `factories.py`, `constants.py`, `test_users.py` (per-instance `make_*_headers` builders for the three `entity_backed` roles).
- `fixtures.py` (792 lines) — 5 tiers: step helpers → program skeleton → staffed sessions → window phase progression → 9 named scenario builders.

**`test_suite/`** (Stage 2, 3,500 lines)
- `conftest.py` + `test_01`…`test_10` organized by domain concern.

## Counts

- **84 test functions → 94 collected** (one parametrized 11-way over the not-found vocabulary).
- **Queue A (Difficulty): 18/18 instances translated**, exactly 2 tests each (36 tests). Zero skipped.
- **Queue B (Corner): 47/47 non-stub instances translated** (≥1 test each). Zero skipped.
- **11 `excluded_because:` stubs not translated**; all 11 `difficulty_instance` cross-references verified to resolve.

## PRD-first filter — assertions dropped (instance still translated)

1. `Corner/entities/server_minted_system_fields_are_not_client_settable` — dropped "POST with an extra `id` key returns 400". PRD §2.7 check 5 enumerates what body well-formedness covers and unknown-field rejection is not among it.
2. `Corner/entities/session_computed_seat_fields_are_derived_not_supplied` — same reasoning for "supplying `seats_consumed` returns 400". Kept all derived-value assertions.

Additionally, **absolute `version` literals were restated as relative** (`v_after == v_before + 1`) in the three instances that asserted them. The PRD never pins the initial version value, but §2.4 + §2.8 + §3.3 make the *delta* uniquely derivable. No instance was lost.

## Stage-2 self-audit results (all clean)

- Every test docstring ends with exactly **one** `Design:` line; all 84 tags resolve to real non-stub instances; no dual-tagged or untagged tests.
- **200 PRD quotations checked** — every one survives a whitespace-normalized literal match against `PRD.md`.
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere.
- No "scaffold" / "Table N" / "§1.x" leakage in generated code.
- All 10 modules import cleanly under `PYTHONPATH=.`; `pytest --collect-only` succeeds.

## Step 7: Run tests and iterate — 2026-08-17T05:05:43.637Z

All 8 parallel rounds now pass at 94/94.

**Iterations run: 2** (sweep → diagnose → fix → sweep). Iteration 1: 89/94 in all 8 rounds, 5 failing tests, identical set every round (no flakiness — all failures were deterministic). Iteration 2: 94/94 in all 8 rounds.

**Tests deleted: none.** Every failing test survived STEP 1 (PRD verbatim-covers + unique derivability). No assertion was weakened, no skip/xfail added, no error_id downgraded.

### Failure set (union across all 8 rounds of iteration 1)

Two root causes behind five failures:

**A. `created_at` / `updated_at` stamped from wall clock instead of the logical assessment clock** — `test_resource_identifier_is_a_bare_server_minted_uuid`, `test_logical_clock_starts_at_the_fixed_instant_and_is_settable`.

STEP 1 verdict: PRD §2.5 states, as a full sentence with a universal quantifier, *"Every timestamp the server stamps — `signed_at` on an affidavit, … and `report_delivered_at` — is read from that logical clock"*, closing with *"it never falls back to real wall-clock time."* §2.4 declares `created_at`/`updated_at` among the four *system-managed* properties, i.e. timestamps the server stamps. The em-dash list is appositive, not restrictive: reading it as exhaustive makes the sentence self-contradictory. Unique derivability holds — implementation bug. STEP 3 fix applied.

**B. Irregularity report filed by a proctor not assigned to the named session** — `test_newly_created_rows_sit_in_their_declared_initial_states`, `test_submitting_an_already_submitted_report_is_refused`, `test_report_adjudication_and_attendance_belong_to_different_roles`. All three failed identically with `ERR_SCOPE_VIOLATION` during setup.

STEP 2 verdict: the implementation's scope check is PRD-required — §2.7 lists *"irregularity report creation"* among the write endpoints ownership scope (check 4) applies to, §2.1 says a Proctor's *"ownership checks compare the resource's proctor-bearing field to `X-User-ID`"*, and §3.7 says *"A `Proctor` files one against the session being run."* The three test setups created a bare `DRAFT` session with `proctor_id` null and then filed from an unrelated proctor — a request the PRD-faithful implementation correctly rejects. TEST IS WRONG; the check stays, the setups were made PRD-faithful.

### Fixes applied to `implementation/`

- `implementation/db.py` — `create()` and `touch()`: `stamp = wall_now()` → `stamp = now()`, and `entity["updated_at"] = wall_now()` → `now()`, so both common-property timestamps read the logical assessment clock per PRD §2.5. Ordering stays deterministic because `sort_key` already tie-breaks equal `created_at` by insertion sequence, which matches §2.3's ascending-creation rule and §3.9's ascending-`created_at` distribution walk.
- `implementation/timeutil.py` — `wall_now()` docstring corrected; it is now used only for the envelope's `api_request_timestamp` (governed separately by §2.2).

### Fixes applied to `test_suite/`

- `test_05_registration_lifecycle.py` — `test_newly_created_rows_sit_in_their_declared_initial_states`: assign the (trained, affidavit-holding) proctor to the session via `assign_proctor_to_session` before filing the report; added the import. Assignment does not change the session's `DRAFT` status, so the initial-state assertions are untouched.
- `test_08_irregularity_workflow.py` — `test_submitting_an_already_submitted_report_is_refused` and `test_report_adjudication_and_attendance_belong_to_different_roles`: setups switched from `setup_program` + bare `add_proctor` + unstaffed `create_session` to `setup_program_with_certified_proctor` + `setup_staffed_session(..., schedule=False)`, so the filing proctor is the session's assigned proctor. Sessions still sit in `DRAFT`; all assertions unchanged.

### Fixes applied to `test_helpers/`: none

The common-fixture layer was already PRD-faithful on identity threading; the three bugs were local to the individual test setups, so no shared fixture needed changing.

### Verification

94/94 in each of rounds 1–8. No `pytest.mark.skip`/`skipif`/`xfail` anywhere in the suite. Storage remains in-memory dicts only — no SQLite, no JSON dump, no `/tmp` cache, no startup seeding. `results.1..8.json` remain as the passing evidence.

## Step 8: Finalize PRD — 2026-08-17T05:10:15.807Z

`PRD_FINALIZED.md` written at `workspace/PRD_FINALIZED.md`.

## Size delta

| | lines | words | chars |
|---|---|---|---|
| PRD.md | 433 | 12,003 | 91,178 |
| PRD_FINALIZED.md | 433 | 12,072 | 91,598 |
| delta | 0 (0.0%) | +69 (+0.57%) | +420 (+0.46%) |

Two source lines touched (PRD.md line 27 and line 103); no sections added, no prose deleted.

## Changes

- **§2.1 (Proctor ownership scope)** — *revise* — the Proctor ownership enumeration now names irregularity-report filing alongside session transitions / attendance / session-scoped custody as requiring `X-User-ID == Session.proctor_id`, clarifies that for a filing the Session is the one named in the request body, and states that a Session whose `proctor_id` is null matches no principal — `implementation/routes/reports.py:53-57` (with `middleware.py:143-150` `body_reference`).
- **§2.5 (logical clock)** — *revise* — the universal is re-scoped to "every timestamp the server stamps **onto a resource**" and its appositive list now leads with `created_at`/`updated_at` on every resource that carries them — `implementation/db.py:73-76`, `implementation/db.py:94`.
- **§2.5 (logical clock)** — *insert* — one trailing sentence carving the envelope's `api_request_timestamp` out of the rule as the sole exception, read from real wall-clock time — `implementation/response.py:26` (`fmt_iso(wall_now())`), `implementation/timeutil.py:12-16`.

## Per-edit pre-edit search log

**Edit 1 — §2.1 report-filing ownership**
- (a) Subject: what ownership scope (check 4) compares for a `Proctor`, and specifically for `POST /irregularity-reports`.
- (b) Paths enumerated (grepped `require_scope|scope_violation` across all of `routes/`, then read each site): `reports.py:53-57` (filing, body-named session, null `proctor_id` fails), `reports.py:120-124` (transitions, `reporter_proctor_id`, Proctor only), `sessions.py:214-220` (transitions; school branch vs proctor branch), `registrations.py:262-266` (attendance), `materials.py:134-144` (custody: district / school-district / session-proctor branches), `affidavits.py:28-32` (body `proctor_id` == `X-User-ID`), plus non-proctor sites to be sure the sentence stays inside the Proctor clause. Also re-read §2.7 check-4 list and `middleware.py:143-150`.
- (c) Adjustment: two. (i) Scoped the new clause to "the Session named in the request body" rather than a bare "the target Session", because the check reads a body field, not a path segment. (ii) Wrote the null-`proctor_id` consequence as a general statement about the whole enumeration instead of a filing-only aside — it is equally true at `sessions.py:220`, `registrations.py:266`, and `materials.py:144`. Deliberately did **not** claim check 4 fires when the body's `session_id` is missing or unresolvable; the impl defers those to checks 5/6.

**Edit 2 — §2.5 `created_at`/`updated_at` on the logical clock**
- (a) Subject: which clock feeds which server-stamped timestamp.
- (b) Paths enumerated (grepped `now()|wall_now` and `created_at|updated_at` across the whole implementation): `db.py:68-83` `create()`, `db.py:85-97` `touch()`, `db.py:50-52` `now()`; every other logical-clock stamp — `affidavits.py:55`, `proctors.py:93`, `sessions.py:266,287`, `appeals.py:77,128`, `windows.py:239,336`, `reports.py:193`, `materials.py:186,312`, `cascades.py:51`; the only `common_fields=False` caller `materials.py:172-191`; `derive.py:145`; `response.py:9,26`; `serialize.py:10,155`.
- (c) Adjustment: qualified the addition as "on every resource **that carries them**" rather than "on every resource", because `materials.py:190` creates custody entries with `common_fields=False` — they have `created_at` but no `updated_at`, and §2.4 already declares that exception.

**Edit 3 — §2.5 `api_request_timestamp` exception**
- (a) Subject: the clock behind the response envelope's timestamp.
- (b) Paths enumerated: `timeutil.py:12-16` (`wall_now`), grep for `wall_now` → exactly one consumer, `response.py:26` inside `_meta()`, which feeds `object_response`, `array_response`, and `error_response`; cross-checked `routes/clock.py:20` and `errors.py`. Also grepped `test_helpers/` and `test_suite/` for `api_request_timestamp`: zero references.
- (c) Adjustment: widening §2.5 to cover `created_at`/`updated_at` made "every timestamp the server stamps" more likely to be read as swallowing the envelope, which would have been a brand-new mismatch against `response.py:26`. Resolved it two ways at once — narrowed the universal to resource timestamps and added the explicit one-sentence exception.

Root cause B of the Step 7 diff was ruled a test-fixture bug, but the same diff item shows the PRD did not uniquely determine the filing-time ownership comparison, so it is pinned in §2.1 rather than left to reconstruction.

## Step 9: Complete PRD — 2026-08-17T05:20:00.964Z

`workspace/PRD_COMPLETED.md` is written.

## Stats

| | PRD_FINALIZED.md | PRD_COMPLETED.md |
|---|---|---|
| Lines | 433 | 433 (unchanged — every edit is in-paragraph) |
| Chars | 91,264 | 98,973 (**+7,709**) |

**44 changes: 36 ambiguity-pins, 8 mismatch-revisions.** No new sections, no new paragraphs, no new table rows.

## Changes

- §2.1 — insert — ambiguity — layer-2 role guard only engages on a declared enum member; absent/non-string/unknown `to_status`/`event_type` falls through to check 5 — `middleware.py:84-94`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric chars — `response.py:19-20`
- §2.3 — insert — ambiguity — bad `limit`/`offset` (non-integer, out of 1–100, negative) → `ERR_INVALID_REQUEST` 400 — `response.py:56-83`
- §2.3 — insert — ambiguity — insertion-order tie-break on equal `created_at`; `total_count` pre-page, `has_more` = `offset + len(page) < total_count` — `db.py:102-105`, `response.py:37-44`
- §2.3 — revise — **mismatch** — custody events list in the same `created_at` order as every list (reproduces `sequence_no` within a lot), not a special sequence sort — `materials.py:272-287`
- §2.3 — insert — ambiguity — filters are exact-equality, unapplied when absent, never 404; unnamed query params ignored — all `list_*` views
- §2.4 — revise — **mismatch** — `version` starts at 1 and advances **at most once per request** across all cascade hops; a no-change recompute refreshes neither `updated_at` nor `version`; `updated_at` also 3 fractional digits — `db.py:84-99`, `derive.py:196-202,255-262,300-309,328-332`
- §2.5 — insert — ambiguity — `to_iso8601` mandatory + must parse; `current_utc` is the whole `data` payload — `routes/clock.py:16-20`
- §2.6 — insert — ambiguity — unrouted path → `ERR_NOT_FOUND` 404; wrong method → `ERR_METHOD_NOT_ALLOWED` 405, both outside §5 — `app.py:46-53`
- §2.7 — insert — ambiguity — absent/unparseable/non-object body reads as `{}`; explicit `null` == omission — `middleware.py:34-39`, `validators.py:15-19`
- §3.1 — revise — ambiguity — `module_version` mandatory non-empty and discarded; `quiz_score_pct` mandatory number 0.0–100.0 — `proctors.py:86-87`
- §3.1 — revise — ambiguity — stored `quiz_score_pct` is rounded half up to one decimal — `proctors.py:89-90`
- §3.2 — revise — **mismatch** — `to_status` outside the seven → `ERR_INVALID_REQUEST`, not `ERR_INVALID_STATE_TRANSITION`; `reason` discarded — `windows.py:135-140`
- §3.2 — insert — ambiguity — `PLANNED → OPEN`: clock gate screened *before* the lot-shipped gate, which fails `ERR_INVALID_STATE_TRANSITION` — `windows.py:147-157`
- §3.3 — insert — ambiguity — assignment on a non-`DRAFT` session → `ERR_INVALID_STATE_TRANSITION`, after the version pin — `sessions.py:183-185`
- §3.3 — revise — **mismatch** — proctor availability excludes the target session itself — `sessions.py:195`
- §3.4 — insert — ambiguity — `guardian_email` is free text, never format-checked — `registrations.py:73`
- §3.4 — insert — ambiguity — make-up uniqueness counts every registration naming the original, whatever its own `attendance_status` — `registrations.py:128-133`
- §3.4 — insert — ambiguity — `accommodation_codes` is a mandatory field — `registrations.py:208-210`
- §3.4 — revise — ambiguity — non-`REQUESTED` decision → `ERR_INVALID_STATE_TRANSITION`; absent `note` overwrites the field with null — `registrations.py:249-253`
- §3.5 — insert — ambiguity — `RECEIPT` quantity ≠ `quantity_shipped` → `ERR_CUSTODY_CHAIN_BROKEN` (not a body error) — `materials.py:214-215`
- §3.5 — insert — ambiguity — the three reconciliation declarations are mandatory integers ≥ 0 — `materials.py:300-302`
- §3.5 — insert — ambiguity — system report also carries null `registration_id` and a server-composed `narrative` — `materials.py:331-344`
- §3.6 — insert — ambiguity — check-in with nothing outstanding → `ERR_CUSTODY_CHAIN_BROKEN`; excess → `ERR_INSUFFICIENT_MATERIALS` — `materials.py:239-243`
- §3.6 — insert — ambiguity — session `reason` discarded; `to_status` outside the four → `ERR_INVALID_REQUEST` — `sessions.py:223-228`
- §3.6 — insert — **mismatch** — `SCHEDULED → ACTIVE` guards run in §2.7 order (phase → booklets → clock → accommodation), not the narrated order — `sessions.py:256-273`
- §3.6 — insert — ambiguity — attendance against a non-`ACTIVE` room → `ERR_INVALID_STATE_TRANSITION` — `registrations.py:271-272`
- §3.6 — insert — ambiguity — re-recording settled attendance → `ERR_INVALID_STATE_TRANSITION` — `registrations.py:273-274`
- §3.6 — insert — ambiguity — both `ACTIVE → CLOSED` failures are `ERR_INVALID_STATE_TRANSITION`, booklet shortfall included (never `ERR_INSUFFICIENT_MATERIALS`) — `sessions.py:282-285`
- §3.6 — insert — ambiguity — cancelling while booklets are out → `ERR_INVALID_STATE_TRANSITION` — `sessions.py:292-293`
- §3.7 — insert — ambiguity — filing is gated by neither session status nor window phase; `registration_id` need not belong to the session — `reports.py:60-68`
- §3.7 — insert — ambiguity — report `note` discarded; `to_status` outside the five → `ERR_INVALID_REQUEST` — `reports.py:127-129`
- §3.7 — insert — ambiguity — the `system_generated` test runs first and fails `ERR_INVALID_STATE_TRANSITION`, before the return-count cap — `reports.py:147-154`
- §3.7 — insert — ambiguity — `disposition` accepted-and-ignored on non-adjudicating targets, screened as body well-formedness before the edge — `reports.py:128-134`
- §3.7 — insert — ambiguity — all three `INVALIDATE_REGISTRATION` failures are `ERR_INVALID_STATE_TRANSITION`, in that order — `reports.py:168-177`
- §3.7 — insert — ambiguity — all three `INVALIDATE_SESSION` failures are `ERR_INVALID_STATE_TRANSITION` — `reports.py:178-184`
- §3.7 — insert — ambiguity — both `BREACH_CONFIRMED` failures are `ERR_INVALID_STATE_TRANSITION`; a missing active affidavit skips that hop and the cascade continues — `reports.py:185-189`, `cascades.py:45-49`
- §3.8 — insert — ambiguity — `SCORING → MAKEUP` leaves `registered_distinct_count`/`present_distinct_count` untouched — `windows.py:207-217`
- §3.8 — revise — **mismatch** — `raw_score` is an integer; registration dimensions (`NOT_SCORED`, `PRESENT`) screened *before* the window phase, session-`CLOSED` *after* it, all three as `ERR_INVALID_STATE_TRANSITION` — `registrations.py:288-302`
- §3.9 — insert — ambiguity — the unscored-present-student release blocker is `ERR_INVALID_STATE_TRANSITION` — `windows.py:229-237`
- §3.9 — insert — ambiguity — appeal-filing scope: school coordinator ↔ session `school_id`, district coordinator ↔ that school's `district_id` — `appeals.py:246-254`
- §3.9 — revise — **mismatch** — appeal filing gates run in §2.7 order: score status before window phase — `appeals.py:263-276`
- §3.9 — revise — **mismatch** — registration status is *not* a precondition on deciding an appeal; a mid-appeal invalidation still decides normally and leaves the registration alone. Also: `corrected_raw_score` is an integer, ignored on `DENIED`, screened before the appeal's status; `note` discarded — `appeals.py:325-351`
- §3.9 — insert — ambiguity — both finalization blockers (open appeal, open report of any category) are `ERR_INVALID_STATE_TRANSITION` — `windows.py:256-266`

## Cross-checks

45 impl endpoints ↔ 45 PRD table rows: exact match, no drift either way. All 40 error IDs and HTTP statuses in `errors.py:12-53` match §5 verbatim. All eight calculation constants (`derive.py:18-35`) match the §3.4/§3.5/§2.9 narratives. Tests were used only as auxiliary corroboration; no assertion drove any edit.
