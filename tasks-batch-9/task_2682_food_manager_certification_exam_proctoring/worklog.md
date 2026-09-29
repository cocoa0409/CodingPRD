# Worklog — task_2682_food_manager_certification_exam_proctoring

## Step 1: Create task directory — 2026-09-04T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2682_food_manager_certification_exam_proctoring` and `.../workspace`. Index 2682 was pre-assigned by the orchestrating command; no scan of `./tasks/` was performed (concurrent pipelines on this host would collide on auto-allocation).

## Step 2: Scaffold generation (§1.0–§1.9) — 2026-09-04T00:00:00.000Z

Generated the three scaffold artifacts from the scenario text plus `skills/prd-bench-scaffold-generator/SKILL.md` only (no sibling task under `./tasks/` was listed, read, or grepped):

- `SCAFFOLD.yaml` — 3048 lines: 14 entities, 6 state machines (ExamSession carries two parallel dimensions), 2 §1.2.1 OCC rules, 12 calculations, 51 prioritised validations, 66 endpoints, 65-entry error catalog, 5 roles (4 `entity_backed`, PlatformAdmin `opaque`).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2608 lines: 9 `rule_id`s × 2–3 instances = 22 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 5741 lines: 9 guide sections, 85 instances (59 with full `test_recipe`, 26 `excluded_because` stubs each citing a resolvable §1.8 `rule_id / name`).

Self-checks: no duplicate `name` across the union of both design files; every stub citation resolves; every `${var}` in every `payload:`/`as_user_id:`/path is bound by an earlier `captures:` in the same instance; every non-placeholder `ERR_*` in the catalog is triggered by at least one instance.

`scaffold_lint.py` final verdict: `clean lint` — 1370 calls scanned across 22 §1.8 + 59 §1.9 instances; all conform to §1.5 and all §1.1 FKs have reverse-reachability.

## Step 3: Copy shared files — 2026-09-04T07:51:00.000Z

Copied `./INSTRUCTION.md` (1424 bytes) to `workspace/INSTRUCTION.md`. No subagent.
## Step 4: PRD generation — 2026-09-04T00:00:00.000Z

Generated `workspace/PRD.md` from `SCAFFOLD.yaml` plus `skills/prd-bench-doc-generator/SKILL.md` only. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened or grepped, so no §1.8/§1.9 worked-example numbers or `test_recipe` asserts could leak into the prose.

- 494 lines / 102,467 bytes, written as 9 chunked appends (no one-shot Write, so no 64k-cap truncation). Ends at the final §5 row `ERR_INSUFFICIENT_CREDIT | 402`.
- Structure: §1, §2.1–§2.11, §3.1–§3.9, §4 (66 data rows), §5 (64 data rows). §2.2 byte-identical to `section-2.2-response-structure.md`.
- Hard Contract 1 (field-name coverage) PASS: entities[].fields 131/131, request_body 82/82, query_params 24/24.
- Hard Contract 2 (rule coverage) PASS after one repair — the `ASSIGNED → ATTESTED` precondition `proctor_attestation == true` was missing from §3.6 and was added.
- Hard Contract 3 (§3 path purity) PASS: 1010 backtick tokens scanned in §3, 0 `/`-prefixed, 0 bare HTTP methods, 0 method+path combos.
- All 64 error ids also appear in §2/§3 narrative (the 14 `ERR_*_NOT_FOUND` ids required an enumerating paragraph in §2.10).
- Note: the §1.6 catalog holds **64** errors, not the 65 recorded in the Step 2 note above.
- Scaffold contradictions resolved toward §1.1/§1.4 rather than the error catalog prose: `suspended_reason` enum has no `AUDIT_REVOCATION`, so the audit-close cascade is described without it; `ERR_DUPLICATE_APPROVED_ACCOMMODATION` scoped to *any* other APPROVED request (validations[38] + state machine) rather than same `accommodation_type`; `ERR_CANDIDATE_SECURITY_HOLD` and `ERR_PROCTOR_NOT_REGISTERED` scoped to their `validations[].applies_to` lists; `ERR_VOIDED_ITEM_COUNT_INVALID` uses validation 40's strict `voided_item_count < scored_item_count`.

## Step 6: Generate implementation — 2026-09-04T08:43:00.000Z

(Steps 5 and 6 were launched concurrently in a single assistant message, so the impl generator was physically unable to read `test_suite/` — that directory did not exist at its spawn time.)

Subagent summary, verbatim:

The implementation is complete and verified.

## Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_2682_food_manager_certification_exam_proctoring/workspace/implementation/`

## Per-file line counts (3,337 lines total, 17 .py files + start.sh + requirements.txt)

| lines | file |
|---|---|
| 10 | start.sh (chmod +x, guarded pip install, `exec python3 app.py`) |
| 1 | requirements.txt (`Flask==3.0.3`) |
| 75 | app.py (8 blueprints, `before_request` -> `store.begin_request()`, ApiError/HTTPException handlers) |
| 117 | store.py (in-memory dicts, pinned logical clock, per-request idempotent version bumps) |
| 76 | errors.py (all 64 error ids -> HTTP status) |
| 78 | envelope.py (meta/response_type/data envelope, pagination) |
| 274 | validation.py (enum vocabularies + shape validators) |
| 154 | authz.py (header auth, entity-backed identity, 404 resolvers) |
| 205 | calc.py (money, discounts, restock fees, allowed_minutes, risk variants, occupancy) |
| 233 | cascade.py (ledger, batch conservation, depth-4 invalidation cascade) |
| 23 | helpers.py |
| 238 | routes_core.py (jurisdictions, providers, exam forms, sites, clock hook) |
| 274 | routes_people.py (candidates, proctors, audits, reinstatement) |
| 261 | routes_codes.py (batches, assignments, void, course completion) |
| 152 | routes_accommodations.py |
| 491 | routes_sessions.py (schedule, reschedule, assignment, check-in, start, submission, cancellation) |
| 232 | routes_scoring.py (score reports, finalization, certificates, recert) |
| 170 | routes_registrations.py (local registrations) |
| 273 | routes_incidents.py (security incidents + the 4-phase compliance run) |

## Endpoint routing: 66 / 66
`ast.parse` passes on all 17 modules. A programmatic diff of Flask's `url_map` against the PRD §4 table gives **66 vs 66, zero missing, zero extra**. All 64 PRD error ids exist in `errors.py` and every one is raised somewhere in the code. No SQLite / file-write / `/tmp` / pickle references; store is empty at boot with no seeding.

## Smoke test (port 39682, killed by its own PID)
Booted clean; drove two full end-to-end business flows plus the cascade:
- Pricing: 25 x EXAM_ONLY = 90000 - 5% volume discount = **85500 cents**, provider ledger balanced.
- Scheduling: IN_PERSON 120 min -> end +2h; REMOTE 120 + 10 setup = **130 min**.
- Scoring: raw 70/80 -> provisional 88; finalization with 2 voided/1 correct -> 69/78 = **88 FINAL, pass**.
- Certificate: 60 calendar months (2026-09-05 -> 2031-09-05), `recert_window_opens_at` = -180 d, 1500-cent fee charged.
- Local registration FILED -> POSTED -> VERIFIED with `posting_deadline_at` = filed + 30 d.
- Compliance run (201): expired 1 batch, 1 certificate (candidate -> LAPSED), dispatched `T_LAPSED` to exactly 1 certificate.
- Incident cascade: filed 201 -> review-open -> resolution rejected 403 `ERR_SEGREGATION_OF_DUTIES` for the finalizing admin, accepted for a second admin -> session INVALIDATED/COMPROMISED, report VOIDED, certificate REVOKED/`SCORE_VOIDED`, registration WITHDRAWN, candidate NON_COMPLIANT + security_hold, proctor risk 50.0 -> SUSPENDED/`RISK_THRESHOLD_BREACH` with reserved_minutes released, provider credited back 1500.
- Envelope/auth checks: 401 `ERR_UNAUTHENTICATED`, 403 `ERR_UNAUTHORIZED`, 400 `ERR_INVALID_PAGINATION`, 404 for unknown routes, 405 for wrong methods.

Server shut down with a targeted `kill` on the single PID holding port 39682 (confirmed closed via `connect_ex` = 111); no pattern kill was used. `__pycache__` removed.

Two PRD-internal contradictions resolved in favour of the majority reading: `id_document_expires_on` equal to the clock date passes (PRD "on or after" + scaffold priority-21 check `>=` outvote the catalogue's "on or before"), and `GET /jurisdictions` is deliberately absent (PRD declares only POST and GET-by-id), so a list call there correctly answers 405.

## Stage 2 complete — test_suite/ (design-index-only)

- 21 files under `test_suite/` (conftest + test_01..test_20), 7,671 lines across
  `test_helpers/` + `test_suite/`, **113 tests / 81 distinct `Design:` tags**.
- Coverage: queue A 22/22 live instances (53 tests), queue B 59/59 live instances
  (60 tests); the 26 `excluded_because` corner stubs were not translated. Zero skips.
- Every docstring carries exactly one trailing `Design:` line; all PRD quotes verified
  greppable against `workspace/PRD.md` (0 BAD lines). `pyflakes` clean, `ast.parse` clean.
- Recorded PRD-over-design deviations: `ERR_INVALID_REQUEST` asserted as HTTP 400 (PRD
  §5) not 422; jurisdiction `accepts_remote_proctoring` defaults true; `GOVT_PHOTO_ID`
  used in place of the design's `DRIVER_LICENSE`; the DEPLETED-batch assignment call in
  `batch_assignment_rejections_*` omitted (design expects `ERR_BATCH_STATE_INVALID`,
  PRD line 246 mandates `ERR_BATCH_DEPLETED`); the second sitting in
  `candidate_security_hold_*` given its own proctor so the CRITICAL substantiation's
  risk recompute cannot release it to PENDING_REPROCTOR; dismissal test asserts the
  finalized sitting at `CLOSED` (PRD §3.7) rather than the design's `SUBMITTED`.

## Step 5: Generate unit tests — 2026-09-04T09:20:00.000Z

Subagent summary, verbatim:

Both stages are complete and verified.

## Output location
`/home/ubuntu/github/CodingPRD/tasks/task_2682_food_manager_certification_exam_proctoring/test_helpers/` and `.../test_suite/` — both at the **task root**. `find` confirms exactly two such directories exist; `workspace/` contains only `INSTRUCTION.md`, `PRD.md` and the (untouched, separately generated) `implementation/`. No stray copies.

## Per-file line counts

test_helpers (1,974 lines): `types.py` 455, `fixtures.py` 431, `factories.py` 291, `api_client.py` 289, `assertions.py` 214, `api_errors.py` 141, `constants.py` 72, `test_users.py` 46, `__init__.py` 35.

test_suite (5,697 lines / 113 tests): `conftest.py` 50 - `test_01_batch_pricing_and_void_refunds` 141/6 - `test_02_scoring_and_equating` 172/6 - `test_03_proctor_audit_risk` 200/5 - `test_04_session_state_dimensions` 208/5 - `test_05_invalidation_and_expiry_cascades` 215/6 - `test_06_validation_precedence` 251/6 - `test_07_cross_entity_state_dependencies` 258/6 - `test_08_occupancy_rules` 187/4 - `test_09_conservation_invariants` 197/4 - `test_10_boundary_values` 215/5 - `test_11_entity_surface` 441/11 - `test_12_state_machines` 477/10 - `test_13_calculations` 427/8 - `test_14_validations` 310/6 - `test_15_endpoints` 333/5 - `test_16_error_surface` 495/6 - `test_17_error_surface` 536/6 - `test_18_rbac_and_scope` 269/4 - `test_19_cross_cutting_layers` 231/3 - `test_20_consistency_model` 84/1.

## Coverage tally (design-index-only)
- **Queue A (§1.8 difficulty): 22 / 22 live instances translated, 0 skipped** — 53 tests.
- **Queue B (§1.9 corner): 59 / 59 live instances translated, 0 skipped** — 60 tests. The 26 `excluded_because` stubs were correctly not translated (entities 11/0, state_machines 10/4, calculations 8/8, validations 6/3, endpoints 5/1, errors 12/8, rbac 4/0, cross_cutting 2/2, consistency_model 1/0).
- **No instance was skipped**, so there is no skip list. A machine diff of tag-names against both YAMLs reports `uncovered live: none` and `tags not in live set: none` in both queues.

## Verification
- `ast.parse` over all 30 emitted files: OK. `pyflakes` on `test_suite/*.py`: clean (rc 0); `test_helpers/*.py` clean apart from the intentional re-export warnings in the `__init__.py` barrel.
- Citation checker over all 21 suite files: **113 tests / 81 distinct design tags, zero BAD lines** — every >=40-char quoted docstring span greps verbatim in `workspace/PRD.md`, every test carries exactly one trailing `Design:` line, no dual tags, no dangling tags.

## Work finished this session
`test_18_rbac_and_scope.py` (rbac 3-4: the segregation-of-duties bar where the finalizer may open the review but not resolve it; the five out-of-scope `ERR_FORBIDDEN_RESOURCE_SCOPE` calls each paired with their in-scope success), `test_19_cross_cutting_layers.py` (both OCC guards — replayed `expected_batch_version`/`expected_session_version` yield 412 and bump no counter, retry with the fresh version succeeds; the four-phase compliance run where phase 2 withdraws the registration before phase 3 can mark it delinquent, `T_LAPSED` is the only tier appended, and the replay at the unchanged epoch returns all zeros), and `test_20_consistency_model.py` (issuance complete in its own 201 response plus four immediately-settled reads).

## Recorded PRD-over-design deviations (also logged in `worklog.md`)
`ERR_INVALID_REQUEST` asserted as HTTP 400 per PRD §5, not the design's 422; `accepts_remote_proctoring` defaults true; `GOVT_PHOTO_ID` replaces the design's non-existent `DRIVER_LICENSE`; the DEPLETED-batch assignment call in `batch_assignment_rejections_*` was omitted (design expects `ERR_BATCH_STATE_INVALID`, PRD line 246 mandates `ERR_BATCH_DEPLETED`) with every other assertion of that instance kept; the second sitting in `candidate_security_hold_*` was given its own proctor so the CRITICAL substantiation's risk recompute cannot release it to `PENDING_REPROCTOR`; the dismissal test asserts the finalized sitting at `CLOSED` per PRD §3.7 rather than the design's `SUBMITTED`.

## Step 7: Test-and-fix iteration loop — 2026-09-04T09:45:00.000Z

Three iterations, each an 8-round parallel `prd-bench-local-run` sweep under
`setsid nohup` (no early exit; union of failures taken across all 8 rounds).

- Iteration 1: 73/113 in all 8 rounds — fully deterministic, no flakiness anywhere in the loop.
- Iteration 2: 112/113 in all 8 rounds.
- Iteration 3: **113/113 in all 8 rounds.**

**No test was deleted.** Every failing assertion traced to a verbatim PRD
sentence and survived the unique-derivability check; all 40 failures were test-side
defects. **The implementation was not modified at all.**

### Fixes to `test_helpers/`

- `api_client.py` — `ApiClient._request` now canonicalises every ISO-instant string in
  the response body to whole-second precision before tests compare it. The PRD fixes the
  *instant* each `*_at` field carries but not its sub-second rendering width: §2.2
  declares three fractional digits for `created_at`/`updated_at`/`api_request_timestamp`,
  while §2.4 spells the very same logical clock as `2026-08-01T00:00:00Z` with none, and
  every other timestamp is only "ISO 8601 UTC". Both spellings are PRD-faithful, so the
  suite must not depend on the choice. This fixed 33 of the 40 failures without touching a
  single asserted value. (`parse_iso` in `fixtures.py` already tolerated both forms, so the
  ambiguity was known to the generator but leaked into 73 inline literal comparisons.)
- `fixtures.py` — `setup_sitting()` and `setup_terminal_sittings()` now re-read the batch
  before returning it in `env["batch"]`. Redeeming the code at check-in mutates the batch's
  counters, and §2.2 says `version` "increments by exactly 1 on every mutation of that
  resource", so the assignment-time copy was stale and the next version-guarded write got a
  correct `ERR_STALE_BATCH_VERSION`.

### Fixes to `test_suite/`

- `test_13_calculations.py` (2 call sites) — the `/access-codes` list filter was sent as
  `access_code_batch_id`; §3.3 names it `batch_id`. The unknown param was ignored, so
  `total_count` counted both batches (39, not 20).
- `test_06_validation_precedence.py` `_two_finalized_reports_on_an_empty_wallet` — both
  sittings are now scheduled before either is checked in. Checking the first in pins the
  clock to 2026-09-10T09:00:00Z, after which the second sitting's 11:15 start could no
  longer clear §3.5's 1,440-minute lead-time floor (setup died on
  `ERR_SCHEDULE_LEAD_TIME_TOO_SHORT`).
- `test_17_error_surface.py` `test_the_second_certificate_waits_for_the_first_ones_recert_authorization`
  — the clock is pinned back to 2026-09-12T10:30:00Z before issuance. Walking the second
  sitting had left it on the 13th, and §3.7 makes `issued_at` the logical clock, while all
  three window figures the test asserts are projected from the 12th. §2.4 explicitly allows
  setting the clock backwards.
- `test_08_occupancy_rules.py` `test_an_adjacent_sitting_is_free_and_a_remote_sitting_never_takes_a_seat`
  — the remote sitting's proctor hold was asserted at 120; §3.5 adds "10 minutes of remote
  setup time for a REMOTE sitting" to `allowed_minutes` and §2.9 sums `allowed_minutes` into
  `reserved_minutes`, so the correct figure is 130. Added an explicit
  `allowed_minutes == 130` assertion alongside it.

No `skip`/`xfail` was added, no `error_id` assertion was downgraded, and no
implementation check was removed or weakened.

## Step 8: Finalize PRD — 2026-09-04T09:50:00.000Z

Step 8 was NOT skipped: although Step 7 applied 0 `implementation/` fixes, it ran 3 iterations with
`test_helpers/` and `test_suite/` fixes, so the skip condition (zero iterations beyond baseline) was
not met. Subagent summary, verbatim:

PRD_FINALIZED.md is in place with a single insertion.

## Line counts
- `PRD.md`: 494 lines / 102,467 bytes
- `PRD_FINALIZED.md`: 496 lines / 103,347 bytes -> +2 lines (+0.40%), +880 bytes (+0.86%)

## Change set (1 edit)
- **§2.4 "Common Resource Properties, Timestamps and the Logical Clock"** — *insert* — new paragraph after the "Timestamps the server writes are never client-supplied..." paragraph pinning the single rendering shape for every server-emitted instant: `YYYY-MM-DDTHH:MM:SS.mmmZ` (exactly three fractional digits, literal trailing `Z`), explicitly covering `created_at`/`updated_at`, `api_request_timestamp`, `current_utc` and every `*_at` field (clock-set or derived); sub-millisecond precision truncated not rounded; unset nullable `*_at` renders `null`; date-only `id_document_expires_on` stays `YYYY-MM-DD`. Impl: `implementation/store.py:16-21` (`iso3`), `store.py:24-35` (`jsonable`), `implementation/envelope.py:14-17,20-26,29-40,43-49`.

## Pre-edit search log
**(a) Subject:** sub-second rendering width / textual shape of every ISO-instant value the API emits (the one PRD silence in `<step_7_diff>`, source of 33/40 failures).

**(b) Impl paths enumerated (grepped/read, not just the Step 7 site):**
- `grep -rn "isoformat\|strftime\|utcnow\|replace(microsecond\|timespec"` over all `.py` -> only serializer is `store.py:21` `d.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (d.microsecond // 1000)`; the only other hits are *input* parsing (`validation.py:203,231`) and a date-string comparison (`routes_sessions.py:326`), neither of which renders an instant.
- `store.jsonable` — sole datetime->string conversion, applied recursively to dicts/lists/tuples; underscore-prefixed keys dropped; `Decimal`->float.
- `envelope.py` — all three response builders (`ok`, `ok_list`, `error_response`) route through `jsonable`; `_meta()` renders `api_request_timestamp` with `iso3(now_wall())` (wall clock, still three digits).
- `grep -rn "jsonify\|make_response\|json.dumps"` -> hits only in `envelope.py`; `app.py` error handlers all delegate to `error_response`. No response bypasses the envelope.
- Every `*_at` writer enumerated: `store.py:88,89,96,99` (`created_at`/`updated_at`), `routes_codes.py:75,91-93,156,258`, `routes_sessions.py:143-155,256-258,364-365,384,419,428,458,482`, `routes_scoring.py:81,166-173,230`, `routes_registrations.py:56-58,111,139,164-166`, `cascade.py:232`, `routes_people.py:124-125` (projected certificate instants) — all are Python `datetime` or `None`, so all render through `iso3`; none is a date-only string.
- Clock hook `routes_core.py:231-237` — echoes `{"current_utc": moment}` through `ok`, i.e. also `iso3`, and `store.clock` retains full microsecond precision (`validation.parse_datetime`), so rendering truncates while stored precision is preserved.
- Date-only surface: `grep -o "`[a-z_]*_on`" PRD.md` -> `id_document_expires_on` only; stored verbatim as a validated `YYYY-MM-DD` string (`validation.req_date_string`).

**(c) Wording adjustments made to stay consistent with all enumerated paths:**
- Added "whether it was set from the logical clock or derived" so the sentence covers `scheduled_end_at`, certificate `expires_at`, `recert_window_opens_at`, `posting_deadline_at` and the `routes_people.py` projections, not just clock-stamped fields.
- Added "however the same instant may happen to be spelled in the prose examples elsewhere in this document" instead of editing the bare-second literals at §2.4 (`2026-08-01T00:00:00Z`) and the endpoint table — avoids touching descriptions of clock *values* while removing the contradiction that produced the ambiguity.
- Scoped the truncation clause to *rendering* only ("rendered by dropping the extra digits") — an earlier draft that also asserted comparisons use the full stored instant was dropped because `calc.truncate_minute` (`calc.py:78`, used by both occupancy rules) compares at whole-minute granularity per §2.9, so that claim would have been a new mismatch.
- Added the "renders as `null`" clause because `iso3(None)` returns `None`, and many `*_at` fields are initialised null (`routes_sessions.py:152-155`, `routes_codes.py:91-93`, `routes_scoring.py:173`, `routes_registrations.py:58`).
- Carved date-only fields out explicitly so the universal claim does not sweep in `id_document_expires_on`.

## Items deliberately not patched
`fixtures.py` stale-batch re-read (§2.4 version rule + §2.8 "each written entity has its own `version` incremented" already pin it), `batch_id` filter name (§3.3 line 244 names `batch_id`; impl `routes_codes.py:220` agrees), lead-time ordering in test_06 (§3.5 1,440-minute floor), backwards clock in test_17 (§2.4 explicitly allows it), and remote 130-minute hold in test_08 (§3.5 line 268 gives the +10 remote allowance and cap-last ordering; §2.9 line 136 sums `allowed_minutes` into `reserved_minutes`; impl `calc.compute_allowed_minutes` matches exactly). All five were test-side defects against already-determined prose.

## Step 9: Complete PRD — 2026-09-04T10:35:00.000Z

**Orchestrator decision recorded here (autonomous, no user available):** Step 9 was run as THREE
sequential file-partitioned passes over the 17 implementation modules rather than one subagent.
Rationale: a single-pass scan of 3,337 lines of implementation against a 103KB PRD reliably comes
back shallow — often byte-identical to its input, which means the scan never actually walked the
code. Partitioning by module guarantees every module is read. All three passes shared the same
prompt contract (implementation is the alignment target; tests are auxiliary only; SCAFFOLD*.yaml
and worklog.md withheld; Edit-only so the 100KB+ file cannot be truncated; NO-NEW-MISMATCH
pre-edit enumeration before every edit). Passes ran strictly sequentially because they all edit
the same file, and each later pass received the earlier passes' hand-off list of behaviours they
had noticed but deliberately left in the later pass's territory.

Partition:
- Pass A — `app.py`, `store.py`, `errors.py`, `envelope.py`, `validation.py`, `authz.py`, `helpers.py`, `routes_core.py`
- Pass B — `calc.py`, `routes_people.py`, `routes_codes.py`, `routes_accommodations.py`
- Pass C — `routes_sessions.py`, `routes_scoring.py`, `routes_registrations.py`, `routes_incidents.py`, `cascade.py`

Totals: **65 edits — 52 ambiguity-pins, 10 mismatch-revisions** (Pass A 14+2, Pass B 16+3, Pass C 22+5).
`PRD_FINALIZED.md` 496 lines / 103,347 bytes -> `PRD_COMPLETED.md` 502 lines / 140,407 bytes
(**+6 lines, +37,060 bytes**). Nearly all edits are in-paragraph, hence the large byte delta on a
tiny line delta. No new sections; heading count unchanged at 28; §5 error table still 64 data rows;
file still ends on the `ERR_INSUFFICIENT_CREDIT` row (not truncated).

### Pass A (globals / envelope / auth / validation / core routes) — 14 pins, 2 mismatches
- §2.1 revise — whitespace-only headers rejected; `X-User-ID` taken verbatim, no trimming — `authz.py:60-65`
- §2.2 revise — `api_request_id` = `req_` + 20 chars `A-Z0-9`, minted per response incl. errors; `api_request_timestamp` reads the host **wall** clock, not the logical clock — `envelope.py:13-17`, `store.py:111-117`
- §2.3 revise — non-integer `limit`/`offset` -> `ERR_INVALID_PAGINATION`; whitespace stripped; empty string == omitted -> default — `envelope.py:52-73`
- §2.3 revise — `created_at` ties broken by a global monotonic creation sequence (insertion order), never exposed and never `id`; `has_more` formula; offset >= `total_count` -> empty `data` with full `total_count` — `store.py:104-105`, `envelope.py:29-40`
- §2.3 insert — empty-string filter == absent; bad enum filter -> `ERR_INVALID_REQUEST` at priority 4 (before pagination); booleans accept `true/false/1/0` case-insensitively; identifier filters unresolved -> empty page, not 404 — `validation.py:249-274`
- §2.3 insert — entity-backed list narrowing: omitted self-scope filter substituted with caller's own id; foreign value -> `ERR_FORBIDDEN_RESOURCE_SCOPE`, not an empty page — `helpers.py:15-19`
- §2.4 revise — `version` increments at most once per resource per request while `updated_at` refreshes every time; a row created in a request stays at `version` 1 — `store.py:65-101`, `app.py:37-39`
- §2.4 insert — no underscore-prefixed field is ever serialised; store empty at start-up (nothing seeded) — `store.py:24-36,43-62`
- §2.4 insert — client-supplied instants parse tolerantly (`Z`/`z`, numeric offsets normalised, **naive read as UTC**, any fractional precision); blank/unparseable -> `ERR_INVALID_REQUEST` — `validation.py:196-220`
- §2.5 insert — list-valued enum fields must be non-empty arrays of declared members, stored in supplied order, duplicates accepted — `validation.py:237-246`
- §2.7 insert — money/percentages/multipliers/`risk_score` serialise as bare JSON numbers (Decimal->float), so trailing zeros are lost; comparisons use the stored two-decimal value — `store.py:24-28`
- §2.8 revise — each cascaded entity's `version` rises by exactly 1 once, however many cascade steps write it — `store.py:94-101`
- §2.8 insert — `code` = `FMC-` + 8 zero-padded digits, `certificate_number` = `CERT-` + 8, each from its own process-wide counter from 1, globally sequential, never per-batch — `store.py:74-80`
- §2.10 item 3 revise — **MISMATCH**: priority 3 is not a global stage. Path resources resolve first (unresolvable path id -> 404 even for an out-of-scope caller); body resources only after full shape validation (priority 4 beats 3); a body FK naming the caller's own entity is compared **before** resolution, so a foreign nonexistent id -> 403 — `authz.py:1-7,56-85`
- §2.10 item 4 insert — body parsing rules: absent/empty/`null` -> empty object; non-object rejected; UTF-8 JSON regardless of `Content-Type`; explicit `null` == omitted; integer fields accept `5.0` but reject booleans; decimal fields accept a number or its string spelling, decimal-place check before range — `validation.py:55-193`
- §3.1 inserts — duplicate `jurisdiction_code` -> 400 `ERR_INVALID_REQUEST`, case-sensitive, after all shape rules; provider `contact_email` only `@`-tested with **no** uniqueness constraint (unlike candidate/proctor); credit adjustment requires `amount_cents` >= 0 and a >=1-char `memo` that is **not persisted**, answers 200; exam-form triple-key collision -> 400 while a 1- or 2-component repeat is legal — `routes_core.py:35-38,72-77,109-117,126-141`
- §5 preamble insert — **MISMATCH**: `ERR_INVALID_REQUEST` is the one id not bound to a single status (unmatched path 404, bad method 405, unparseable body 400), all produced **before** header inspection, so an unauthenticated call to a bad path is 404 not 401; trailing slash insignificant — `app.py:30,45-65`

### Pass B (calc / people / codes / accommodations) — 16 pins, 3 mismatches
- §2.9 insert — site overlap comparison also truncates both interval ends to the whole minute — `calc.py:174-189`
- §2.10 item 6 revise — **MISMATCH**: PRD ordered shape (4) before path resolution (6); impl resolves every path identifier before the body is read at all, so an unresolvable path id beats a malformed body — verified across all 8 route modules
- §3.2 insert — candidate create: FK order (provider then jurisdiction) after shape-check; `training_provider_id` compared to `X-User-ID` before resolution -> 403 even for a nonexistent provider; `email` uniqueness exact/case-sensitive/cross-provider -> `ERR_INVALID_REQUEST` after both FKs resolve — `routes_people.py:25-38,76-84`
- §3.2 insert — compliance-summary: active-certificate selection (`ISSUED`>`EXPIRED`>`REVOKED`, `SUPERSEDED` ineligible, most-recently-minted within a status), all-null fallback, `local_registration_status` = most recent filing whatever its status, `open_incident_count` definition — `routes_people.py:88-131`
- §3.2 insert — proctor create: same before-resolution 403; `email` uniqueness error code, case-sensitivity, independence from the candidate address space — `routes_people.py:142-153`
- §3.2 insert — proctor listing scope 403 precedes the `registration_status` shape-check — `routes_people.py:190-193`
- §3.2 insert — `decision_note`/`audit_reason`/`audit_note`/`remediation_ref` are shape-validated then **discarded**, persisted nowhere; mandatory ones fail before the state gate — `routes_people.py:206,225,242,267`
- §3.2 insert — audit population: sittings tied on both instants keep minting order (stable descending sort), so the rolling-window pair is determined — `calc.py:118-124`
- §3.2 insert — reinstatement recomputes no risk; `risk_score`/`risk_variant_applied` survive untouched — `routes_people.py:262-274`
- §3.2 insert — suspension-release cascade moves only the proctor's counter: the sitting stays `SCHEDULED` and keeps its seat — `cascade.py:103-117` (applied in Pass C)
- §3.3 insert — purchase: `training_provider_id` compared before resolution, then provider then form resolve with their own 404s — `routes_codes.py:44-54`
- §3.3 insert — batch persists/echoes `line_items` in request order; batch row precedes its codes in the creation sequence; 201 carries the batch alone — `routes_codes.py:64-99`
- §3.3 insert — batch-listing scope 403 precedes the remaining filters' shape-check — `routes_codes.py:113-117`
- §3.3 insert — **[Pass A hand-off]** `batch_id` is the only *resolved* filter platform-wide; its 404/403 outrank `ERR_INVALID_PAGINATION`; omitted `batch_id` -> post-filter chain trimming — `routes_codes.py:220-234`
- §3.3 insert — assignment: path batch resolved+scope-checked before the body; candidate-vs-batch provider mismatch -> `ERR_FORBIDDEN_RESOURCE_SCOPE` after `candidate_id` resolves and before the version guard; with a pinned clock the creation sequence, not `created_at`, decides the winning code — `routes_codes.py:128-153`
- §3.3 revise — **MISMATCH**: PRD claimed assignment rejects an already-`ASSIGNED`/`CONSUMED` code with `ERR_ACCESS_CODE_STATE_INVALID`; the endpoint names no code and never raises it — an empty pool always answers `ERR_BATCH_DEPLETED`
- §3.3 revise — **MISMATCH**: PRD claimed an `EXAM_ONLY` code keeps `course_completed_at` null for its whole life; sign-off applies no `bundle_type` condition, so an `EXAM_ONLY` code can be signed off. Also pinned: instructor FK resolves before the code-state gate; `CONSUMED`/`VOIDED`/`EXPIRED` also answer `ERR_ACCESS_CODE_STATE_INVALID` — `routes_codes.py:240-249`
- §3.3 insert — void: only `VOIDED`/`EXPIRED` hit the state gate so a `DEPLETED` batch falls through to `ERR_BATCH_DEPLETED`; `reason` validated then discarded, fails before any version or state check — `routes_codes.py:171-181`
- §3.4 inserts — `Candidate` self-check precedes resolution (403 even for a nonexistent candidate) while `ProviderAdmin` scope is compared after `ERR_CANDIDATE_NOT_FOUND`; `accommodation_type`/`requested_language` are inert record fields; `reviewed_by_user_id` written on the review-open hop only and never rewritten by the decision; duplicate gate evaluated **before** the multiplier comparison so both violations answer `ERR_DUPLICATE_APPROVED_ACCOMMODATION`; occupancy tests all run before any write and read siblings at pre-approval intervals, any single failure refuses the whole decision; on denial a supplied `approved_multiplier` is shape-checked, ignored and never stored — `routes_accommodations.py:28-41,90,112-152`
- §3.7 insert — `add_months` carries time-of-day across and clamps to the target month's last day (29 Feb + 12 months -> 28 Feb) — `calc.py:108-113`

### Pass C (sessions / scoring / registrations / incidents / cascade) — 22 pins, 5 mismatches
- §2.10 item 3 insert — added the `reported_by_proctor_id` a Proctor supplies when filing an incident to the own-entity-FK compared-before-resolution list — `routes_incidents.py:40`
- §3.5 insert — scheduling: six body FKs resolve in listing order, `candidate_id` 403 precedes the other five; sessions-list `proctor_id` own-scope 403 raised after both enum filters are shape-checked, still ahead of pagination — `routes_sessions.py:91-99,184-185`
- §3.5 insert — proctor-assignment applies only the exclusive occupancy rule (`ERR_SITE_SEAT_CAPACITY_EXCEEDED` unreachable); security_hold, lead time, jurisdiction, site languages and form status are not re-checked; `proctoring_status` set to `ASSIGNED` outright; re-assigning the same proctor is a ledger no-op that does not write the proctor row — `routes_sessions.py:279-304`
- §3.5 insert — reschedule: omitted vs explicitly-`null` semantics for `delivery_mode`/`testing_site_id`/`proctor_id`, departing from §2.10 item 4; null `proctor_id` detaches and leaves `proctoring_status` as-is — `routes_sessions.py:208-218`
- §3.5 insert — reschedule re-reads only `accepts_remote_proctoring`, not accreditation/language/form status; occupancy self-exclusion is by identity not early release; no reserved-minute counter moves until every check passes — `routes_sessions.py:236-252`
- §3.5 insert — an effective non-null `proctor_id` moves `PENDING_REPROCTOR`/`PENDING_ASSIGNMENT` -> `ASSIGNED`; every site/proctor row the release or reservation touches is written even at zero net delta, so an unchanged proctor's `version` still increments — `routes_sessions.py:260-267`
- §3.5 insert — cancellation `reason` mandatory, min length 1, no upper bound, shape-checked at priority 4 then discarded — `routes_sessions.py:470`
- §3.6 insert — `_session_scope`'s acting flag: the `proctor_id` comparison is skipped on the three acting writes when `proctor_id` is null so the request reaches `ERR_SESSION_PROCTOR_UNASSIGNED`, while a plain GET of the same sitting still answers `ERR_FORBIDDEN_RESOURCE_SCOPE` — `routes_sessions.py:19-30`
- §3.6 revise — **MISMATCH**: only a date strictly before the clock's own day is `ERR_ID_DOCUMENT_EXPIRED`; compared between the two `YYYY-MM-DD` spellings, so a document expiring today is accepted — `routes_sessions.py:326`
- §3.6 insert — `biometric_match_score` stored null when omitted from an IN_PERSON check-in; a supplied `proctor_attestation` is recorded on either channel and omission leaves the stored flag unchanged — `routes_sessions.py:316-317,361-363`
- §3.6 insert — a false `proctor_attestation` still submits, stores false and leaves `proctoring_status` `ASSIGNED`; a code no longer `ASSIGNED` is left alone and the submission still succeeds; the batch's own `status` is never changed by a consumption; the 201 `data` is the newly minted score report, not the sitting — `routes_sessions.py:414-461`
- §3.7 insert — **MISMATCH**: the report's own state gate is evaluated ahead of the sitting's notwithstanding the numeric order of §2.10, so a second finalization answers `ERR_SCORE_REPORT_STATE_INVALID` — `routes_scoring.py:58-62`
- §3.7 insert — certificates-list `jurisdiction_id` own-scope 403 raised after the `status` filter is shape-checked, still ahead of pagination — `routes_scoring.py:204-206`
- §3.7 insert — supersession walks prior certificates `created_at` ascending with the §2.3 tie-break and supersedes the **most recently minted** qualifier; an `EXPIRED` certificate with null `recert_authorized_at` qualifies for nothing — `routes_scoring.py:132-146`
- §3.8 insert — `establishment_name`/`establishment_address` mandatory min-1 strings, no max, no format; no uniqueness on them or on `certificate_id`, so a certificate may accumulate any number of registrations; registrations-list `jurisdiction_id` own-scope 403 ordering; `posting_location` mandatory min-1 with no ceiling — `routes_registrations.py:36-37,83-85,102`
- §3.8 revise — **MISMATCH**: `rejection_reason` is optional even on the `REJECT` branch (null when absent; empty string is a priority-4 violation), and the certificate-`ISSUED` requirement is tested on the `VERIFY` branch alone — `routes_registrations.py:124-129`
- §3.9 insert — filing: `reported_by_proctor_id` compared to `X-User-ID` before either identifier resolves, then `exam_session_id` resolves first and `reported_by_proctor_id` second; the filer need not be the sitting's proctor and its own `registration_status` is never looked at; the incidents-list own-scope filter shows a Proctor only what it filed while a single read is wider (filed **or** currently assigned) — `routes_incidents.py:19-28,40-43,84-85`
- §3.9 insert — **MISMATCH**: the incident gate precedes the sitting's notwithstanding §2.10, so a second review-open answers `ERR_INCIDENT_STATE_INVALID`; the hop takes no body — `routes_incidents.py:100-103`
- §3.9 revise — added the accommodation `reviewed_by_user_id` segregation-of-duties comparison alongside `finalized_by_user_id`; `resolution_note` optional, stored null when omitted — `routes_incidents.py:126,138-145`
- §3.9 insert — invalidation releases nothing: neither `reserved_seat_minutes` nor `reserved_minutes` is adjusted, so an interval still held from an unfinalized submission stays held while one already released by finalization is not released twice — `cascade.py:170-172`
- §3.9 revise — a compliance-run sweep cancellation deducts `allowed_minutes` from both counters but, unlike an operator's cancellation, leaves the proctoring dimension untouched rather than moving it to `CLEARED` — `routes_incidents.py:182-187`
- §4 revise — **MISMATCH**: `/compliance-runs` description reordered to the actual phase order (expires batches -> expires certificates -> marks delinquent postings -> sends reminders) — `routes_incidents.py:262-265`

### Deliberately left unpinned (recorded so a later reader does not mistake these for misses)
- `void_credit_buckets` (`cascade.py:39-48`) — `repair + remainder == net_credit_cents` always, so the two-bucket split posts identically to a single credit and is unobservable through the API.
- Unreachable branches: `ERR_CANDIDATE_NOT_FOUND` / `ERR_TRAINING_PROVIDER_NOT_FOUND` mid-cascade in `issue_certificate`; the `cycle_months` 60 and `posting_deadline_days` 30 fallbacks; the first-match report selection in `substantiate` (a sitting can only ever own one report).
- Pass C verified the four remaining precedence chains against the §2.10 ladder and found them already ascending, so no further inversions exist beyond the three revised above.

### Final integrity verification (run by the orchestrator, not the subagents)
- `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (899 changed 100-col segments) and `PRD_FINALIZED.md` is not identical to `PRD.md` — both patches genuinely ran.
- 28 headings, §5 table still 64 data rows, file ends on the `ERR_INSUFFICIENT_CREDIT` row.
- No stray `worklog.md`, `test_helpers/` or `test_suite/` under `workspace/`; `test_helpers/` and `test_suite/` are at the task root as required.
- Step 7's 8-round sweep evidence re-read after Step 9: `results.1..8.json` all `passed=113 / total=113 / failed=0`. Step 9 edits touched only PRD prose, never `implementation/` or the tests, so the green sweep still stands.

**PIPELINE COMPLETE — `workspace/PRD_COMPLETED.md` written.**
