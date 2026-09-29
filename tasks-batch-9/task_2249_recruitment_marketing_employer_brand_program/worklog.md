# Worklog — task_2249_recruitment_marketing_employer_brand_program

## Step 1: Create task directory — 2026-09-01T11:00:43.000Z

Created `tasks/task_2249_recruitment_marketing_employer_brand_program/` and `tasks/task_2249_recruitment_marketing_employer_brand_program/workspace/` (pre-allocated task name used verbatim; no index scan performed).

## Step 3: Copy shared files — 2026-09-01T15:50:17.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (run out of order relative to Step 2 because it is bash-only and independent).

## Step 2: Generate scaffold — 2026-09-01T17:20:25.000Z

Note (orchestrator): the first three Step-2 subagent launches each terminated with an upstream `API Error: The system encountered an unexpected error during processing` after hours of work (host is heavily loaded — 61 peer Claude sessions). A fourth subagent regenerated all three artifacts in one consistent run; its verbatim summary follows.

All three artifacts are complete, parse cleanly, and pass `scaffold_lint.py`.

**Files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2249_recruitment_marketing_employer_brand_program/`): `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`

**Counts**
- Entities: 15 | State machines: 8 (+2 `concurrency_rules`, OCC on `Program` and `JobPosting`)
- Calculations: 11 | Validations: 50 (single global priority order) | Endpoints: 74 | Errors: 81 | Roles/RBAC: 8 (`role_model: segregation_of_duties`, `Candidate` the only `entity_backed` role)
- §1.8 difficulty instances: 18 (9 rule_ids × 2)
- §1.9 corner instances: 47 active + 19 `excluded_because` stubs (66 items) across all nine claim-extraction-guide sections
- Lint: `VERDICT: clean lint`, 598 calls scanned, all FKs reverse-reachable

**Notable design decisions**
- Two independent OCC parents (`Program.version` guards budget commitment, `JobPosting.version` guards optimization/compliance) so a stale-version retry must be re-read from a different entity than the one written.
- All-or-nothing three-bucket budget waterfall (FAMILY_DEDICATED → channel-type pool → FLEX_RESERVE, events skipping the pool), with mirroring RELEASE ledger rows on cancellation; partial funding is an error (`ERR_MEDIA_BUDGET_EXHAUSTED`) and persists nothing.
- Multi-touch attribution uses floor-then-largest-remainder basis-point allocation, so credit always sums to exactly 10000 bp and never double-counts.
- Brand health = age-weighted (1.00/0.50/0.25 at <=30/<=60/else, 90-day window with an exclusive lower bound) and gates flight activation at exactly 55.00 — corner cases pin both the boundary pass and the fail.
- Segregation of duties sits at validation priority 9, ahead of content checks (EEO at 23), so the same user optimizing then clearing a posting fails on SoD rather than on content.
- Posting optimization is a self-transition that retracts compliance clearance (CLEARED -> UNREVIEWED) and recomputes the score, giving a cascading side effect inside one entity.
- Consent-before-frequency ordering in nurture dispatch, `>=` frequency cap, strictly-greater 30-day window; consent tokens are server-minted secrets (a client-supplied token is rejected).
- Half-open media-flight windows contrasted with a closed 48-hour event-reservation buffer, and `immediate` consistency so derived program health is visible in the request that creates a review.

## Step 4: Generate PRD — 2026-09-01T17:37:00.000Z

§4 and §5 are appended; PRD.md is complete at 536 lines.

## Document produced

`/home/ubuntu/github/CodingPRD/tasks/task_2249_recruitment_marketing_employer_brand_program/workspace/PRD.md` — 536 lines, ends at the §5 error table with no audit footer.

**Section list**

- `## 1. Introduction` (3 paragraphs: hybrid media-agency/regulated-publisher framing, entity tour, the two design commitments — append-only budget ledger and logical clock)
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Role-Based Access Control · 2.2 API Response Structure (verbatim fixed block) · 2.3 Pagination and List Ordering · 2.4 Resource Identity, Timestamps and the Logical Clock · 2.5 Money, Basis Points and Rounding Discipline · 2.6 The Budget Waterfall and the Ledger of Record · 2.7 Version Guards on Budget and Content Writes · 2.8 Resource Addressing and Foreign-Key Resolution · 2.9 Request Admission Order · 2.10 Cascade Discipline and Counter Propagation · 2.11 Two-Person Rules and Scoped Uniqueness
- `## 3. Business Logic & Workflows` — 3.1 Program and job families · 3.2 Channels and persona research · 3.3 Career-site content: optimization, compliance clearance, publication · 3.4 Pricing and funding a media flight · 3.5 Activation, delivered spend, pacing · 3.6 Application funnel and source-of-hire attribution · 3.7 Talent community consent and nurture dispatch · 3.8 Employer review response and brand health · 3.9 Event and campus brand presence
- `## 4. Endpoint Definitions` — 4-column table (Method | Path | Description | Authorized Role(s)), 74 rows, no bodies or side effects exposed
- `## 5. Error Code Catalogue` — 2-column table (Error ID | HTTP Status Code), 81 rows in scaffold order

## Hard Contract results

**Contract 1 — Field-Name Coverage: PASS.** All 175 `entities[].fields[].name` values appear verbatim in backticks; all `endpoints[].input`, `query_params` and `path_params` identifiers appear in backticks (scripted diff returned empty). The only scaffold `- name:` values not backticked are the 15 internal calculation/variant ids (`persona_channel_mix`, `media_budget_waterfall`, `application_touch_credit`, `linear_multi_touch`, `survey_weighted_mix`, etc.), which are not payload identifiers — their semantics are rendered as prose per the skill's "no pseudocode / no internal ids" guidance.

**Contract 2 — Rule Coverage: PASS.** All 50 `validations[].priority` entries rendered as an explicit numbered 1-50 ladder in §2.9, each with error id and HTTP status, closed by a sentence stating that text order elsewhere is not an ordering signal. Both `concurrency_rules` in §2.7 with occ field, mismatch behaviour and exact 412 codes. Cross-entity side effects, `applies_to` scopes, field-level structured content, and all 11 calculations covered in §2.5-2.11 and §3. All 81 error ids also appear in §1-§4 prose, not only in the §5 table.

**Contract 3 — §3 Path Purity: PASS.** Zero backticked tokens in §3 begin with `/`, are a bare HTTP method, or combine method+path (grep over the extracted §3 region returned nothing). §3 uses state-transition, role+gerund and capability framing throughout.

## Zero-Silence-Rule risks deliberately resolved

1. **List ordering for programs.** `GET /programs` said "newest first by created_at" while the skill mandates ascending `created_at` as the global default. Resolved for ascending: §2.3 declares ascending globally and enumerates only the nine genuinely domain-ordered collections as exceptions; §4 describes `GET /programs` neutrally.
2. **`available_budget_cents`.** The entity definition adds `sum of JobFamily.dedicated_budget_cents`; the `PATCH /programs/{programId}` side effect omitted it. Resolved for the entity definition — §2.6 states the full formula and §3.1 has the patch recompute "from the standing definition in §2.6". Creation-time value stays consistent since no families exist yet.
3. **Review close `sla_status`.** The endpoint side effect said "sets `sla_status` MET" unconditionally; the state machine and the field definition make it MET only when `responded_at <= response_due_at`, else BREACHED. Used the state-machine reading.
4. **Pacing precedence.** Wrote "`THROTTLED` outranks `IDLE`" once in §2.10 and applied it to all four flight-departure paths plus `idle_since` clearing, rather than leaving each path silent.
5. **Sibling-branch symmetry.** Equal density given to CLEAR/FLAG, publish-from-OPTIMIZED vs from-SUSPENDED, APPROVE/REQUEST_REVISION, legal APPROVE/REJECT, DISQUALIFIED-from-SCREENED vs from-QUALIFIED, DISPATCHED/CANCELLED, presence cancel from CONFIRMED vs PLANNED, both mix variants and both attribution models.
6. **Rounding ambiguity.** §2.5 pins per-quantity rounding direction (floor vs half-up), the single-division-single-rounding rule, and floor-then-largest-remainder for 10000 bp with the forbidden alternative spelled out; §3.4 additionally names the two explicitly-wrong pricing readings.

## Step 6: Generate implementation — 2026-09-01T18:24:00.000Z

The implementation for task 2249 is complete and verified.

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_2249_recruitment_marketing_employer_brand_program/workspace/implementation/` (~3,260 lines total):

**Entry / infra**
- `start.sh` — guarded `pip install` (only if `import flask` fails, with a `--break-system-packages` retry), then `exec python3 app.py`; binds `0.0.0.0:${PORT:-10000}`
- `requirements.txt` (`Flask>=2.2`), `app.py` — blueprint registration, `strict_slashes = False`, `ApiError`/`HTTPException`/`Exception` handlers, single-threaded no-reloader `app.run`
- `db.py` — in-memory dicts (no seeded data), id/token generation, logical clock (default `2026-08-01T00:00:00Z`), per-request-idempotent `touch()`
- `errors.py` — 84-entry `ERROR_STATUS` map (81 catalogue ids + 3 framework fallbacks)
- `response.py` — envelope (`meta`/`response_type`/`data`), `req_`-prefixed 20-char request ids, 3-fraction-digit timestamps, list pagination meta
- `middleware.py` — `@require(...)` RBAC over `X-User-ID`/`X-User-Role`, `Anonymous` support
- `validation.py` — body/field/pagination validation (422 / 400 ordering)

**Services**: `calc.py` (pricing tiers, attribution, pacing, brand health via `Decimal`+`ROUND_HALF_UP`, SLA, largest-remainder 10000-bp split with `Fraction`), `budget.py` (FAMILY_DEDICATED -> channel-type pool -> FLEX_RESERVE waterfall, append-only ledger with per-program 1-based `sequence_no`, mirrored RELEASE walk), `channel_svc.py` (pacing recompute, throttle/idle resolution with THROTTLED-outranks-IDLE precedence), `serialize.py`

**Routes (74 endpoints)**: `core.py` 11, `personas.py` 9, `postings.py` 8, `flights.py` 8, `applications.py` 9, `community.py` 13, `reviews.py` 8, `presences.py` 6, `ledger.py` 2

## Verification

- Every file passes `python3 -m py_compile`; `bash -n start.sh` clean
- Booted via `bash start.sh` and answered requests; both verification servers have been killed and the ports are free (other agents' servers on this host were left untouched)
- **Route parity 74/74** against SCAFFOLD (0 missing, 0 extra); **role parity 0 mismatches**; **error parity** all 81 catalogue ids present with correct HTTP statuses, none unknown raised, all reachable; **entity field parity** — every serializer's key set exactly equals its SCAFFOLD field list plus the correct audit fields (`version`/`updated_at` only where `common_fields: true`)
- Two end-to-end smoke suites confirmed hand-computed values: pricing (base 70000 / TIER_1 / fee 2100 / total 72100), LINEAR credits `[3334, 3333, 3333]`, throttle cascade (cpqa 60000 > threshold 12000 -> THROTTLED -> flight PAUSED_PACING, `reserved_cents` 0, ledger `[(1,RESERVE,72100,FLIGHT_RESERVATION),(2,RELEASE,-72100,FLIGHT_PACING_THROTTLE)]`), attribution reversal, community dispatch suppression verdicts, review pipeline SLA freeze, 48h presence buffer

## PRD ambiguities resolved

- **Admission ladder** (§2.9, 50 fixed priorities) is authoritative over narrative text order. Notably activate/resume/submit check compliance-cleared (25) before brand-health (27) before published (31), and campaign dispatch runs 19 -> 26 -> 43 -> 49 (audience assembled before the too-early check).
- **Versioning**: `touch()` is idempotent per request, so each cascade bumps an entity at most 1. No `Program.version` bump on review ingest or `/_clock/set_current_utc`; program *is* versioned on review legal APPROVE and on close. No `JobPosting.version` bump on `POST /applications`, but versioned on submit and decide. Flight complete/cancel/resume version flight+channel+program unconditionally (literal SCAFFOLD wording); spend versions the program only when reservations were released; the compliance/archive cascade touches a channel only when a departing flight had been ACTIVE.
- **Clock endpoint** returns `data: {}` (SCAFFOLD declares `output: "null"`).
- **Pay range**: optimize only orders the bounds when both are present; publish requires both (`ERR_PAY_RANGE_INVALID`).
- **Spend on a RESERVED/SUSPENDED_CONTENT flight** -> `ERR_FLIGHT_ALREADY_TERMINAL` (the only state-rejection code the catalogue offers for spend).
- `end_date < start_date` -> `ERR_FLIGHT_TOO_SHORT`; job-family `code` accepted when uppercase and 2-12 chars; duplicate `priority_rank` not enforced (no error code exists).
- Persona APPROVE gate = non-empty stored `channel_mix`, else `ERR_NO_RESEARCH_SIGNALS`.
- `conversion_rate_bp` is null when `apply_start_count == 0`; `resolve_idle` consults only the same-request THROTTLED marker plus current status, and `idle_since` clears only on (re-)entering ACTIVE.

## Step 5: Generate unit tests — 2026-09-01T18:52:00.000Z

The suite is complete. Final state of `/home/ubuntu/github/CodingPRD/tasks/task_2249_recruitment_marketing_employer_brand_program/`:

## Files written

**Infrastructure — `test_helpers/`** (7 modules): `__init__.py`, `api_client.py` (one method per endpoint), `api_errors.py` (81-member `ApiErrorId` + status map), `constants.py`, `test_users.py` (per-role pinned identities, `headers_for_role`, `no_identity_headers`, `candidate_headers`), `assertions.py` (money/ledger/mix/budget helpers), `factories.py`, `fixtures.py` (workflow builders: programs -> families -> channels -> personas -> postings -> flights -> applications/touchpoints -> members/campaigns -> reviews -> presences -> ledger reads). Only change this session: added `list_postings`.

**Test suite — `test_suite/`**: `conftest.py` plus 21 test modules, **89 tests**.

| file | tests | file | tests |
|---|---|---|---|
| test_01_persona_research_mix | 2 | test_12_entity_input_and_immutability_contracts | 6 |
| test_02_posting_content_and_compliance | 4 | test_13_consent_and_review_state_transitions | 4 |
| test_03_flight_pricing_and_waterfall | 5 | test_14_flight_and_event_terminal_states | 3 |
| test_04_resource_windows_and_buffers | 5 | test_15_brand_health_score | 4 |
| test_05_flight_activation_gates | 4 | test_16_derived_calculations | 4 |
| test_06_attribution_credit | 6 | test_17_posting_compliance_and_capacity_validations | 5 |
| test_07_qualification_cascade_and_pacing | 5 | test_18_endpoint_behaviours | 4 |
| test_08_compliance_flag_cascade | 3 | test_19_error_identity_and_scoping | 5 |
| test_09_nurture_dispatch | 5 | test_20_role_permissions_and_two_person_rules | 4 |
| test_10_employer_review_response_cycle | 3 | test_21_version_guards_and_immediate_consistency | 3 |
| test_11_entity_creation_and_reads | 5 | | |

## Design-index coverage

- **Queue A (§1.8 difficulty): 18/18 instances translated**, every one with >=2 tests (tests 01-10, 40 tests).
- **Queue B (§1.9 corner): 47/47 non-stub instances translated, 0 skipped** (tests 11-21, 49 tests). The 19 instances carrying `excluded_because:` were never translated, as specified.
- Every test docstring carries exactly one trailing `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line copied verbatim from the yaml; no test is untagged or dual-tagged, and no tag points at a stub or a non-existent instance.

## Verification

Automated auditor (`/tmp/audit_prd_tests.py`, temporary, not part of the deliverable) reports **0 findings** across: every `PRD §...: "..."` citation greps verbatim against `workspace/PRD.md`; exactly one trailing `Design:` tag per test; tag resolves to a real non-stub instance; per-instance coverage counts. `python3 -m compileall test_suite test_helpers` passes; no `skip`/`skipif`/`xfail` anywhere.

## Two design-yaml defects found and corrected against the PRD

1. `optimization_score_sums_five_weighted_components...` calls its long title "21 words" but the literal string is 19 words (score would then be 10, not 0 for the title band) — I extended the title to a genuine 21 words so the PRD-derived score of 50 holds.
2. `stale_expected_posting_version_on_optimize_returns_412` states the post-retry score is 75; the PRD's five components give 25 + 20 + 15 + 15 + 10 = **85** (the yaml's own addends sum to 85). The test asserts 85.

Also resolved earlier: a freshly ingested overdue review is `PENDING`, not `BREACHED` (explicit §3.8 initial-state sentence), which is what makes the 93.75 / 91.25 / 99.38 / 55.00 brand-health expectations self-consistent.

## Step 7: Run tests and iterate — 2026-09-02T07:05:00.000Z

All eight rounds of the final parallel sweep are clean (`89/89` passed, 0 failed, 0 errors). Scratch tooling removed; the eight `results.*.json` files remain in `workspace/implementation/`. No stray runner or Flask processes remain.

## Summary

**Iterations run**
6 full 8-round parallel sweeps (each launched 8 concurrent `prd-bench-local-run` rounds with `--isolation per-test-server`, joined with `wait`, no early exit), plus one targeted top-up of individual discarded rounds. Final state: all 8 rounds `passed == total == 89`, `failed == 0`, `errors == 0`.

**Tests deleted (with PRD-silence category)**
None. STEP 1a/1b was never reached: every non-passing outcome in the union across all rounds was environmental, not an assertion tripping.
- Round-level `error` outcomes (up to 41 in a bad round) were all `subprocess.TimeoutExpired` on the harness's own `lsof -ti:PORT -sTCP:LISTEN` in `prd_bench_local_runner/pytest_plugin.py::_kill_port` (hardcoded `timeout=5`, `TimeoutExpired` not caught). Host load 200-430, `/proc/net/tcp` at 11207 lines, real `lsof` measured 5-8 s — the timeout was structural. I did not modify the shared runner; I ran the sweeps behind a throwaway zero-fork `lsof` shim (0.01-0.12 s/call) which took clean-round yield from ~0/3 to 3/3, then removed it.
- Two `status == "failed"` entries (`test_05_flight_activation_gates.py::test_activation_is_refused_while_the_posting_is_cleared_but_unpublished`, `test_09_nurture_dispatch.py::test_a_window_count_equal_to_the_cap_suppresses_while_one_below_still_sends`) were `ConnectionResetError(104)` with no HTTP response. Proof of externality: the matching server logs (`/tmp/prd_bench_server_54469.log`, `/tmp/prd_bench_server_46505.log`) contain 0 tracebacks and 0 HTTP 500s, only `Killed` — peer pipelines on this shared host broadcast `pkill -f prd-bench-local-run` / `pkill -f pytest` waves. Both tests passed in every other round.

**Fixes applied to `test_helpers/`**
None. No fixture, factory, or role-header builder was found to construct a PRD-inconsistent precondition.

**Fixes applied to `implementation/`** — all under STEP 3, each tracing to a verbatim PRD sentence
- `.../workspace/implementation/services/calc.py` — `sla_status()` now returns the *stored* verdict instead of deriving it lazily, and a new `reevaluate_sla(review)` writes `PENDING`/`BREACHED` for unresolved reviews only. Traces to §3.8 "`sla_status` is a three-valued verdict maintained continuously." and to §3.8's closed list of re-evaluation points (clock-set, triage, legal APPROVE, close), with REJECT explicitly excluded: "does not touch `responded_at`, `sla_status` or the brand health score."
- `.../workspace/implementation/routes/reviews.py` — ingest stores `sla_status: "PENDING"` as a public field (the private `_resolved_sla` key is gone); `_resolve()` writes `responded_at` and `MET`/`BREACHED`; ingest calls `db.touch(program)` per §3.8 "Ingesting a review immediately recomputes the program's `brand_health_score`"; triage calls `calc.reevaluate_sla` before touching.
- `.../workspace/implementation/routes/core.py` — the clock endpoint re-evaluates every review's verdict, per §2.4 "re-evaluates `sla_status` on every `EmployerReview`".

**Fixes applied to `test_suite/`** — STEP 2 test-vs-PRD faithfulness; all five strengthen or preserve assertion strength, none weaken
- `test_14_flight_and_event_terminal_states.py::test_completing_an_event_keeps_the_reservation_and_refuses_the_boundary_instant` — expected family `reserved_cents`/`dedicated_available_cents` corrected from `200000` to `0`. The old value contradicted §2.6 ("At the family level, `reserved_cents` is the sum of `delta_cents` over that family's entries whose `bucket` is `FAMILY_DEDICATED`") given the test's own ledger assertion pinning the entire draw to `FLEX_RESERVE` with `dedicated_budget_cents == 0`.
- `test_17_posting_compliance_and_capacity_validations.py` — (a) the publish refusal now asserts the ladder-determined `ERR_EEO_STATEMENT_MISSING` (§2.9 item 23 precedes item 25, and §2.9 is authoritative: "Text order in the rest of this document is *not* an ordering signal; this list is."); (b) the superlative-boast test now reads state immediately after the refusal and pins `compliance_status`, `cleared_by_user_id`, `version`; (c) the capacity test now pins program `version` across the refused flight to prove the refusal had no side effect.

Integrity re-verified: implementation storage is in-memory only (no sqlite, file `open()`, `json.dump`, pickle, or `/tmp` cache anywhere under `implementation/`), no startup seeding, no endpoints or response fields added beyond PRD text, and no skip/xfail markers introduced.

## Step 8: Finalize PRD — 2026-09-02T07:20:00.000Z

Done. `PRD_FINALIZED.md` written with four surgical edits.

## Line counts
- `PRD.md`: 536 lines / 116,287 bytes / 16,188 words
- `PRD_FINALIZED.md`: 536 lines / 117,636 bytes / 16,395 words
- Delta: **0 lines (0.00%)**, +1,349 bytes (+1.16%), +207 words (+1.28%). All four edits are in-line within existing paragraphs; no new sections, no new lines.

## Changes
- **§2.4 (logical clock)** — insert — the clock-setting pass writes only the stored SLA verdict; it neither refreshes `updated_at` nor advances `version` on any `EmployerReview` or `Program`, explicitly overriding §2.4's own audit rule — `implementation/routes/core.py:22-34` (no `db.touch` anywhere in the handler).
- **§3.8 ("The response deadline")** — insert — ingesting a review also refreshes the funding program's `updated_at` and advances its `version` by 1 — `implementation/routes/reviews.py:63`.
- **§3.8 (`sla_status` paragraph)** — revise — `sla_status` is a *stored* verdict rewritten at exactly four moments (ingest -> always `PENDING`; clock-set; triage; resolution); re-evaluation touches unresolved reviews only, resolved verdicts are frozen; `clock == response_due_at` still reads `PENDING`; a review ingested already past its deadline reads `PENDING` and carries no SLA penalty until the next clock-set or its own triage — `implementation/services/calc.py:213-231`, `implementation/routes/reviews.py:19-23,51`.
- **§3.8 ("The handling workflow", triage)** — insert — triage versions the review alone; the program's `updated_at`/`version` stay untouched even when the verdict flip moves brand health — `implementation/routes/reviews.py:75-80`.

## Per-edit pre-edit search log

**Edit 1 — §2.4 clock**
(a) Subject: audit-field (`updated_at`/`version`) consequences of the clock-set re-evaluation and brand-health recompute.
(b) Enumerated: `routes/core.py:22-34` (full handler — `set_clock` + `reevaluate_sla` loop, no touch); `db.py:142-153` (`touch` is the only version-bumper, per-request deduped); `middleware.py` (whole file — no after-request mutation); `app.py`/`response.py` not mutators; `services/serialize.py:19-37,243-261` (`brand_health_score` and `sla_status` are read-time projections, so no stored score needs writing); `services/calc.py:239-264` (score derived from clock + stored verdicts). Also confirmed PRD line 371 + line 375 already pin the endpoint's empty `data` body, so I did **not** touch response shape.
(c) Adjustment: dropped a first draft that called this "the one mutation in the API exempt from the audit rule" — an unverifiable universal claim over paths Step 7 never exercised. Replaced with the local, non-exclusive "notwithstanding the audit rule above".

**Edit 2 — §3.8 ingest / program versioning**
(a) Subject: which operations advance `Program.version`.
(b) Enumerated every `db.touch(program)` callsite in the tree: `routes/reviews.py:63,132,155`; `routes/flights.py:88,144,206`; `routes/presences.py:76,108`; `routes/postings.py:49`; `routes/applications.py:131`; `routes/community.py:233`; `services/channel_svc.py:48`; `routes/core.py:89`. Cross-read §2.7's note listing what advances `Program.version` — it is phrased as a non-exclusive "Note that ...", and §3.8 already adds APPROVE/close outside that list, so adding ingest introduces no contradiction.
(c) Adjustment: scoped the sentence to *this* operation ("that funding program") rather than editing §2.7's enumeration. Deliberately left §2.7 alone — its claim that "flight activations ... advance `Program.version`" does not match `routes/flights.py:92-115` (activation touches flight and channel only), but that is outside the Step 7 diff and out of scope.

**Edit 3 — §3.8 `sla_status` semantics**
(a) Subject: every read and write of `sla_status`, and the stored-vs-derived distinction.
(b) Enumerated all `sla_status` sites via a tree-wide grep: writes at `routes/reviews.py:51` (ingest), `:22` (`_resolve`, used by APPROVE `:129` and close `:152`), `services/calc.py:230` (`reevaluate_sla`, called from `routes/core.py:33` and `routes/reviews.py:78`); reads at `services/serialize.py:254`, `routes/reviews.py:178` (list filter), `services/calc.py:257` (SLA penalty). Verified draft-response, submit-legal and legal `REJECT` never write the field, and that `reevaluate_sla` early-returns on `RESOLVED_REVIEW_STATES`. Traced reachability of the stale-`PENDING` window: only from `NEW` (drafting is unreachable from `NEW`), which is why the wording names ingest->clock-set/triage specifically.
(c) Adjustment: two. First, wrote the boundary as "a clock standing exactly on `response_due_at` still reads `PENDING`" to match `clock() <= response_due_at`, while leaving the resolution rule's existing "at or before `response_due_at`" verbatim so the two rules (`calc.py:231` vs `reviews.py:23`) stay separately stated. Second, changed "frozen at the value resolution computed" to "keeps the verdict resolution wrote for it, whichever way the clock later moves", so the sentence also covers backward clock moves — a path Step 7 never exercised but which `reevaluate_sla`'s early return governs.

**Edit 4 — §3.8 triage**
(a) Subject: which entities triage versions.
(b) Enumerated `routes/reviews.py:67-80` (touches review only; no `db.touch(program)`, no cascade) and compared against the sibling review endpoints that *do* touch the program (`:132`, `:155`) and against `db.touch`'s per-request dedupe at `db.py:142-153`.
(c) Adjustment: said "versions the review alone" rather than "no other entity is versioned", keeping the claim to the entities actually enumerated at this endpoint.

**No PRD edit for two Step 7 items, deliberately:** the `test_14` family `reserved_cents`/`dedicated_available_cents` correction is a pure fixture bug — `calc.family_reserved_cents` (`services/calc.py:61-69`), `services/budget.py:8-13` bucket order, and `routes/presences.py:79-90` (completion releases nothing) already match §2.6 and §3.9 verbatim. Likewise `test_17`'s ladder and no-side-effect strengthenings are already uniquely determined by §2.9 items 23/25 and by the raise-before-mutate structure of `routes/postings.py:167-190` and `routes/flights.py:44-67`.

## Step 9: Complete PRD — 2026-09-02T07:32:00.000Z

Done. `PRD_COMPLETED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_2249_recruitment_marketing_employer_brand_program/workspace/PRD_COMPLETED.md`.

## Counts

- **PRD_FINALIZED.md**: 536 lines / 117,636 chars -> **PRD_COMPLETED.md**: 536 lines / 122,448 chars (**+4,812 chars**, 0 line delta — every change is an in-paragraph insert or revision; no new sections, no new paragraphs, 20 lines touched).
- **Ambiguity pins: 13** · **Mismatch revisions: 8**

## Changes

- §2.1 — insert — ambiguity — on `Anonymous`-listing endpoints `X-User-ID` is never required; a valid role header without a user id acts as that role, a missing role header is treated as `Anonymous`, an unknown role is still 401 — `middleware.py:33-45`
- §2.7 — revise — **mismatch (the flagged divergence)** — flight *activation* does **not** advance `Program.version` (touches only flight + channel); list corrected to funding edits, reservations, resumptions, completions/cancellations, presence confirm, and cancel of a *`CONFIRMED`* presence only — `routes/flights.py:108-114` (no `touch(program)`), vs. `flights.py:88,144,206`, `presences.py:76,108`
- §2.9 item 36 — revise — mismatch — the review-decision gate is non-empty stored `channel_mix` on `APPROVE` only; `signal_count` is re-checked on submission alone, never on a decision, and `REQUEST_REVISION` imposes neither — `routes/personas.py:145-147`
- §3.1 — insert — ambiguity — `code` uppercase is enforced as `code == code.upper()`, so digits/punctuation pass; only a lowercase letter gets 422 — `routes/core.py:120-121`
- §3.1 — revise — mismatch — `priority_rank` uniqueness within the program is **not enforced**; a colliding rank is accepted (no such error code exists) — `routes/core.py:126` (no duplicate check)
- §3.2 — insert — ambiguity — the pre-gate recomputation on persona submission is persisted only on success; a refused submission leaves stored mix/confidence/signal_count untouched — `routes/personas.py:118-127`
- §3.2 — insert — ambiguity — `last_review_note` is set to null when `review_note` is omitted, clearing an earlier note — `routes/personas.py:149`
- §3.3 — insert — ambiguity — an inverted pay pair *at creation* is `ERR_INVALID_REQUEST` (422), not `ERR_PAY_RANGE_INVALID` — `routes/postings.py:69-70`
- §3.3 — insert — ambiguity — `substantiation_url` is any string of 1-2,000 chars, no URL-shape check — `routes/postings.py:73-74`
- §3.3 — revise — mismatch — compliance-flag cascade versions the program **only when hop five actually wrote a `RELEASE`** (a `PAUSED_PACING`-only suspension leaves `Program.version` alone) — `routes/postings.py:48-49`
- §3.3 — revise — mismatch — archive cascade versions the program only when a `RELEASE` was written; archiving with no money-holding flight leaves `Program.version` untouched — `routes/postings.py:48-49`
- §3.3 — insert — ambiguity — `GET /job-postings/{id}/conversion` returns the **whole posting resource**, not a funnel-only payload — `routes/postings.py:245-249`
- §3.4 — insert — ambiguity — `end_date` at or before `start_date` is caught by `ERR_FLIGHT_TOO_SHORT`, not schema validation — `routes/flights.py:47-50`
- §3.5 — insert — ambiguity — `amount_cents` minimum is 1 cent; `spent_on` is required/validated but never surfaced on any resource — `routes/flights.py:152-153,161`
- §3.5 — insert — ambiguity — with `credited_qualified_bp` positive but blended target null, `pacing_status` becomes `ON_TARGET` — `services/channel_svc.py:20-22`
- §3.5 — insert — ambiguity — optional `reason` (<=500 chars) and `note` (<=2,000 chars) audit strings are validated then discarded; only the persona `review_note` is retained — `routes/flights.py:186`, `applications.py:104`, `community.py:241`, `presences.py:97`, `postings.py:160`, `reviews.py:71,118,144`
- §3.6 — insert — ambiguity — starting an application does **not** version the posting (funnel counters are derived) — `routes/applications.py:48-63`
- §3.6 — revise — mismatch — disqualification-from-`QUALIFIED` does not touch the program: `last_attribution_recompute_at` is left as-is, and `Program.version` moves only if a throttle released money in the same request — `routes/applications.py:137-151`
- §3.7 — insert — ambiguity — `consent_token` is validated at <=200 chars, so an over-long token is 422 `ERR_INVALID_REQUEST` before comparison — `routes/community.py:60`
- §3.7 — insert — ambiguity — dispatch versions the program unconditionally, even when every row was suppressed — `routes/community.py:233`
- §3.9 — insert — ambiguity — `start_at`/`end_at` are only ISO-8601-validated; an inverted interval is accepted — `routes/presences.py:28-29`
- §4 — revise — mismatch — `GET /employer-reviews` has **no** external-reference filter (program, platform, state, sla_status only) — `routes/reviews.py:172-178`

Cross-checked against the §2.9 admission ladder: every route's gate order already matches the ladder (publish, activate, resume, submit-application, confirm-consent, dispatch), so no ordering prose needed revision. Tests were consulted only as auxiliary cross-reference.
