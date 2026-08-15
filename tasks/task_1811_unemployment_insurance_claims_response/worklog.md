# Worklog — task_1811_unemployment_insurance_claims_response

## Step 1: Create Task Directory — 2026-08-14T18:01:00.000Z

Task directory `tasks/task_1811_unemployment_insurance_claims_response/` and `workspace/` already existed (created by the pipeline launcher); verified via ls. No index scan performed per instructions.

Additional directive from pipeline launcher: **"Generate task hard than expert level!"** — passed through to the Step 2 scaffold-generator subagent as a difficulty directive (target: harder than the skill's expert tier).

## Step 2: Generate Scaffold — 2026-08-14T18:38:30.000Z

All three artifacts are complete and pass the lint with a clean verdict. Here is the summary.

## Task 1811 — Unemployment Insurance Claims Response (employer): scaffold complete

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1811_unemployment_insurance_claims_response/SCAFFOLD.yaml` (§1.0–§1.7 only; no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1811_unemployment_insurance_claims_response/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1811_unemployment_insurance_claims_response/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (77 endpoints, 15 entities, 27 §1.8 + 40 §1.9 active instances, 680 calls scanned, exit 0)

**Counts:** 15 entities; 10 state machines (60 transitions); 7 calculations; 14 validation priorities; 77 endpoints (incl. 2 test-driving: `/_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default, `/_events/claim_adjudication_ack`); 46 error codes; 7 roles (all `opaque`, segregation-of-duties model); 3 OCC concurrency rules.

**§1.8:** 9 rules × 3 instances = **27 instances** (expert floor is 2/rule). **§1.9:** all 9 taxonomy sections, **40 active instances + 1 excluded stub**.

**Harder-than-expert design decisions:**
- Saturated every difficulty rule to 3 instances, each meeting the rule's differentiation clause (3 different entity domains for dual-variant calc — deadline/rating/completeness; modes (a)+(b)+(c) for combinatorial; cycles on UiClaim/TpaEngagement/Hearing; cascades of depth 4, 3, 3 from 3 distinct triggers; 3 different validation-priority pairs; 3 boundary metrics — timestamp-inclusivity, fiscal cap, posture band; 3 cross-entity pairs; 3 interval geometries — buffered adjacency (referee), containment (witness), closed-closed intersection (TPA window); 3 conserved quantities — statement total, reserve ledger, reserve+credit-counter asymmetry).
- Circular-dependency rating formula with pinned 6-step evaluation order, unrounded-ratio tiering, integer-bps liability floor; per-state deadline computation with CALENDAR/BUSINESS variants, federal-holiday list, weekend-shift post-pass, and 17:00Z day-pinning; half-strike posture contagion from denied protests.
- 3 OCC-guarded write endpoints with stale-version tests driven by cascade-bumped versions; all formula-derived asserts pre-computed as literals (verified by executing the formulas in Python, e.g., 2026-08-13 vs 2026-08-17 deadline divergence, 360 vs 270 bps rating divergence, score 55/40/15 evidence totals, reserve round-trips 30000000→29800000→30000000).
- Replay-audited every chain: fixed stale OCC captures after version-bumping line posts, added 4 reverse-reachability GETs, renamed path params to the lint's `{id}` convention, added the WAIVED-line producer (waive endpoint + transition + third invariant), and made reserve debit-at-post / credit-at-reversal / no-reconcile-recredit accounting consistent across the three files.

## Step 3: Copy Shared Files — 2026-08-14T18:39:10.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1811_unemployment_insurance_claims_response/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T19:03:00.000Z

All checks pass. The five "missing" enum tokens are false positives from my scraper — `EIN`, `SSN`, `USPS`, `YYYYQ` are descriptive annotations (rendered in prose: "Federal EIN", "4-digit string", "two-letter USPS code", "a four-digit year followed by Q and a digit from 1 to 4, such as `2026Q2`"), and `END_OF_DAY` is a calculation constant name whose value is fully rendered as "17:00:00 UTC — the end-of-day pin". Neither the contract nor field coverage requires them as backticked identifiers.

PRD generation complete. Summary:

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1811_unemployment_insurance_claims_response/workspace/PRD.md` — 379 lines, 8,242 words. (The forbidden `SCAFFOLD_DIFFICULTY_DESIGN.yaml` / `SCAFFOLD_CORNER_DESIGN.yaml` were never opened.)

**Section list**
- §1 Introduction (2 paragraphs: employer burden/deadline-lattice angle)
- §2.1 Roles (7 roles, all `identity: opaque` translated per-role), §2.2 Response Structure (verbatim — byte-identical match confirmed), §2.3 Pagination, §2.4 Resource Identity/Versioning, §2.5 Logical Clock, §2.6 Deadline Arithmetic (17:00:00Z pin, 11 federal holidays, weekend shift, inclusive boundary), §2.7 Precision Discipline, §2.8 Validation Pipeline (14 tiers in explicit order) & Nested Retrieval, §2.9 OCC (3 rules), §2.10 Employer Standing (reserve/credits/strikes/posture formula)
- §3.1 Employers/StateRules/TPA oversight, §3.2 Separations & coding confidence, §3.3 Intake & response deadline, §3.4 Drafting/evidence/submission, §3.5 Determinations/appeals/hearings/witnesses, §3.6 Statements/protests/reconciliation, §3.7 Rating projection & posture
- §4 Endpoint table (77 rows, 4 columns), §5 Error catalogue (46 rows, 2 columns)

**Coverage audit**
- §1.1 entities: 15/15 — all 112 fields present (deduped 95 unique identifiers required, 95 present, 0 missing, incl. all endpoint inputs, query filters `employer_id`/`state_code`/`status`/`separation_id`, and outputs `current_utc`, rating-summary fields)
- §1.2 state machines: 10/10 machines, 61/61 transitions expressed (from/to states, preconditions paired with error IDs, all side effects incl. cascades); all 45 state values and all enum domains appear as exact backticked strings
- §1.2.1 concurrency: 3/3 OCC rules with write operation + `expected_claim_version`/`expected_statement_version`/`expected_employer_version` + `ERR_STALE_VERSION` (412), framed purely as stale-version rejection, checked last per validation priority
- §1.3 calculations: 7/7 in precise prose (deadline computation incl. BUSINESS-basis day-walk; category-best documentation score with all 7 base weights +10/−5 adjustments; pinned 6-step rating projection with full 7-row rate table, surcharges 20/50, cap 540, exact-rational tiering and floor-last rounding; 5-aggregate audit variance; pinned-order protest evidence score with all 5 basis weights, +20/−25/±10 terms and created_at tie-break; inclusive deadline boundary; half-strike posture formula with inclusive 2.0/4.0 thresholds)
- §1.4 validations: 14/14 priorities rendered as an explicit ordered pipeline in §2.8 with error IDs at each tier
- §1.5 endpoints: 77/77 in §4; every `side_effects` entry rendered in §3 (incl. version increments on draft/submit/evidence-attach/line-post/protest-file/finalize, statement bubble-up, witness freeze, create-with-supersede)
- §1.6 errors: 46/46 in §5 table AND mentioned in §2/§3 prose
- §1.7 roles: 7/7 with exact spelling and per-role identity translation
- Contract 3: 578 §3 backtick tokens scanned — 0 path tokens, 0 bare HTTP methods, 0 method+path combos
- No operator leakage (`>=`, `==`, `+=` …) and no fuzzy hedging words in prose

**Zero-Silence decisions** (behaviors I pinned that the scaffold left implicit):
1. `current_tax_rate_bps` pinned to 270 bps at employer creation until the projection recomputes it (scaffold default 270 + "computed" create side effect)
2. Segregation-of-duties mechanism: drafter's `X-User-ID` recorded internally at draft time (no public created-by field exists) and compared at accept/reject
3. DECIDED_REVERSED reserve credit rendered as exactly one credit per reversed line, reconciling the appeal-level aggregate credit with line-level side effects so no double-credit reading is possible
4. Rate-table top band: ratios above 0.08 fall into the final row (ceiling 1.00) at 540 bps, with the 540 cap making any beyond-table reading unambiguous
5. Hearing closure on appeal withdrawal rendered as `SCHEDULED` or `PREP_IN_PROGRESS` → `CLOSED`, merging the claim transition's "any SCHEDULED hearing" with the Hearing machine's two CLOSED transitions
6. Appeal and protest windows explicitly stated as always calendar days regardless of `window_basis`; EXPEDITED threshold rendered as "no more than 48 hours" (2-day constant, inclusive)
7. `ERR_WINDOW_VIOLATION` scoped to structurally invalid intervals (hearing end not after start); filing lateness expressed via `LATE`/`DISMISSED_UNTIMELY` branches, matching the catalog's "where window is hard" condition
8. Category-level validation IDs (`ERR_TEMPORAL_OVERLAP`, `ERR_AUTHORITY_VIOLATION`, `ERR_INSUFFICIENT_EVIDENCE`) presented in §2.8 as tier labels mapping to their specific §5 catalog instantiations
9. Re-appeal `round_number` pinned to "one greater than the remanded appeal's"; reinstatement `breach_count` reset pinned to one, not zero

All three hard contracts report PASS.

## Step 6: Generate Implementation — 2026-08-14T19:25:00.000Z

Implementation complete. All 100+ smoke checks passed across five test waves, and the server was verified to boot from a fresh process (via the actual `bash start.sh` contract) with zero state each time.

## Summary

**File list** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1811_unemployment_insurance_claims_response/workspace/implementation/`):
- `start.sh` (executable), `requirements.txt` (flask>=3,<4), `app.py` (entry, auth before-request, error handlers)
- `db.py` (empty in-memory dicts for all 15 entities + logical clock), `errors.py` (all 46 catalog error IDs), `response.py` (envelope + pagination), `middleware.py` (X-User-ID / X-User-Role auth, 7 roles), `util.py` (ISO-8601 parse/format, body validators)
- `routes/`: `clock.py`, `state_rules.py`, `employers.py`, `tpa.py`, `separations.py`, `claims.py`, `responses.py`, `evidence.py`, `determinations.py`, `appeals.py`, `hearings.py`, `charges.py`, `models.py`
- `services/`: `core.py` (id/created_at/updated_at/version stamping, serialize), `deadlines.py`, `scoring.py`, `rating.py`

**Endpoints: all 77 from the scaffold §1.5 table implemented** (clock set, adjudication-ack event, state rules, employers + 6 scoped sub-lists + rating-summary, TPA engagement CRUD/actions, separations + coding confirm, claims + filters + withdraw/close, response draft/submit/accept/reject + amendment and evidence reverse lookups, evidence attach/delete (204), determinations, appeals + withdraw/decide (AFFIRM/REVERSE/REMAND), hearings + witnesses + prep ladder + continue/hold, charge statements + line posting + audit/complete/reconcile, protests (file with OCC, review, sustain, deny, withdraw), line waive, rating models create/get/finalize with OCC).

**Calculation/state-machine modules:**
- `services/deadlines.py` — response_deadline_computation (CALENDAR vs BUSINESS bases, 11 fixed 2026 federal holidays, weekend_shift, 17:00:00Z pin), calendar-window deadlines for appeal/protest, inclusive timeliness boundary.
- `services/scoring.py` — documentation_assembly_score (per-category best, +10 auth, −5 post-hoc, cap 100), protest_evidence_score (pinned order: basis weight → DENIED +20 → latest-response LATE −25 → confidence ±10, clamp 0–100), posture_recompute (half-strike per denied protest, inclusive 2.0/4.0 thresholds).
- `services/rating.py` — experience_rating_projection (exact `Fraction` ratio never rounded before tier lookup, 7-row rate table, WATCH +20 / SANCTIONED +50 surcharges, 540 cap, floored integer liability), snapshot hash, DRAFT/FINALIZED supersede invalidation.
- All 11 state machines implemented with their preconditions, side effects, and cascades (late-response strikes + TPA breach auto-suspend at 3, REINSTATED breach reset to 1, amendment supersede chains, DECIDED_REVERSED charge auto-reversal with single reserve credit, reconcile protest-credits accrual without double reserve credit, OCC checked last at 412 on submit/protest/finalize).

**Logical clock:** `db.py` initializes exactly `2026-08-01T00:00:00Z` at boot and never reads wall-clock; `POST /_clock/set_current_utc` (PlatformAdmin) replaces it and echoes `current_utc`; every `filed_at`, deadline comparison, `created_at`/`updated_at`, and the envelope `meta.api_request_timestamp` read this clock.

**start.sh:** guards the pip install behind `python3 -c "import flask"` so per-test reboots skip it, then `exec python3 app.py` in the foreground; `app.py` binds `0.0.0.0:$PORT` (default 10000). Verified: entity created → kill → `bash start.sh` reboot → store empty and clock back at the 2026-08-01 default; `ss` confirms `0.0.0.0` binding.

## Step 5: Generate Unit Tests — 2026-08-14T19:28:00.000Z

Generation complete. Everything is written to disk, compiles, collects (87 tests), and passes all audits.

## Summary

### Outputs
- **`test_helpers/`** (9 files): `types.py` (15 entity TypedDicts + 20 status/role enums), `api_client.py` (83 endpoint methods, one per PRD §4 row), `api_errors.py` (46 error IDs registered with the framework's HTTP-status map), `assertions.py` (per-entity structural assertions), `factories.py` (input-only payload factories), `constants.py` (rate table, score weights, thresholds, holiday list, timestamp presets), `test_users.py` (7 opaque-role header sets with distinct user IDs for segregation-of-duties), `fixtures.py` (composite chains: determined/appealed/docketed/heard claims, statements with lines, protest lifecycle, model finalize with OCC, late-strike accumulators), `__init__.py` barrel.
- **`test_suite/`**: `conftest.py` + 8 numbered test files.

### Test counts by queue — 87 total
| File | Queue A | Queue B | Total |
|---|---|---|---|
| test_01_access_control_and_reference_data.py | 0 | 13 | 13 |
| test_02_deadlines_and_timeliness.py | 4 | 4 | 8 |
| test_03_responses_evidence_and_occ.py | 2 | 7 | 9 |
| test_04_appeals_hearings_and_witnesses.py | 12 | 2 | 14 |
| test_05_determinations_and_claim_closure.py | 4 | 3 | 7 |
| test_06_tpa_engagement_oversight.py | 8 | 2 | 10 |
| test_07_charge_statements_and_protests.py | 8 | 5 | 13 |
| test_08_rating_reconcile_and_posture.py | 10 | 3 | 13 |

Queue A: 48 tests covering 24/27 instances (≥2 each). Queue B: 39 tests covering 36/40 non-stub instances (≥1 each; 3 instances have 2 tests). The one stub (`claim_notice_intake_computes_due_at`) was not translated; its `difficulty_instance` pointer resolves.

### Instances skipped (PRD-first two-condition failures; no placeholders emitted)
- **A `priority_pair_validation_conflict/state_vs_business_temporal_on_submit`** — superseded response on a withdrawn claim admits both `ERR_INVALID_STATE` and `ERR_RESPONSE_NOT_DRAFT` at the same tier with no PRD precedence; lateness on submit is a branch, not an error (§2.8), so the second conflict arm doesn't exist.
- **A `priority_pair_validation_conflict/business_referential_vs_business_fiscal_on_line_post`** — PRD §2.8 tier-5 examples name only `response.claim_id` and claim→separation employer matching; the line→statement employer match isn't PRD-covered, so the priority outcome isn't uniquely derivable.
- **A `cross_entity_state_dependency/statement_reconcile_blocked_by_open_protest`** — reachable setups fail `ERR_STATEMENT_NOT_RECONCILABLE` and `ERR_PROTESTS_IN_FLIGHT` simultaneously (same tier, unordered), or depend on ambiguous bubble-up semantics from `AUDIT_COMPLETE`.
- **B `entities/employer_duplicate_fein_rejected`** — PRD declares fein globally unique but never names the rejection error (400 vs 409 divergence).
- **B `errors/error_tpa_filing_outside_effective_window`** — §3.1 names `ERR_TPA_SCOPE_VIOLATION` at draft time and `ERR_TPA_NOT_ACTIVE` "at the moment of filing" (submit); out-of-window at draft is ambiguous.
- **B `errors/error_terminate_tpa_with_open_work`** — the blocking condition (`RESPONSE_IN_PROGRESS` + `response_channel == TPA`) is unreachable literally, since the channel is stamped at submit; the asserted rejection of an unsubmitted TPA draft isn't uniquely derivable.
- **B `cross_cutting_layers/model_input_stale_on_finalize`** — PRD supports both eager (`DRAFT`→`SUPERSEDED` on input change → `ERR_MODEL_NOT_DRAFT`) and lazy (snapshot check → `ERR_MODEL_INPUT_STALE`) readings.

Two instances were translated with claim-preserving adjustments: `error_line_already_protested` uses an isolated scenario (prior protest WITHDRAWN, then `ALREADY_PROTESTED` basis) because the recipe's literal setup contradicts PRD's error assignment; `expedited_posture_near_deadline` uses a 32-hours-remaining clock because the recipe's literals (56 h) fall outside PRD's 48-hour `EXPEDITED` threshold under the hour-precise reading.

### Tag audit
All 87 tests carry exactly one `Design:` line, copied verbatim from the source YAMLs; all tags resolve to real instances; no stub tags used; no `skip`/`skipif`/`xfail` markers; no scaffold references in generated code. All 125 quoted PRD citation spans survive a literal whitespace-normalized grep of `PRD.md`.

## Step 7: Run Tests and Iterate — 2026-08-14T19:36:00.000Z

All 8 rounds pass 87/87. The task is complete.

## Summary

- **Iterations run:** 2 (sweep 1: 76/87 per round with 11 deterministic failures, identical across all 8 rounds; sweep 2 after fix: 87/87 × 8 rounds, zero failures, zero flakiness).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:** none.

- **Fixes applied to `implementation/`:** 1 root cause, 2 files.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1811_unemployment_insurance_claims_response/workspace/implementation/util.py` — added `fmt_plain()` (ISO-8601 UTC, whole seconds, `...T17:00:00Z`) alongside the existing `fmt_ts()` (three fractional digits).
  - `/home/ubuntu/github/CodingPRD/tasks/task_1811_unemployment_insurance_claims_response/workspace/implementation/services/core.py` — `serialize()`: system-managed `created_at`/`updated_at` keep three fractional digits per PRD §2.4; every other (business) datetime now renders in the plain-seconds form.

**Diagnosis (per protocol):** All 11 failing tests failed on one rendering bug — the serializer emitted `.000Z` on every datetime (e.g., `response_due_at` = `2026-08-13T17:00:00.000Z`). STEP 1a: the asserted values are verbatim PRD rules (17:00:00 UTC pin §2.6, business-day counting §3.3, inclusive timeliness boundary §2.6, `filed_at` stamped from the logical clock §3.4, continuance interval replacement §3.5). STEP 1b: the expected rendering matches PRD's own literals — the clock "reads exactly `2026-08-01T00:00:00Z`" (§2.5) and deadlines pin to "17:00:00 UTC" (§2.6); §2.4's three-fractional-digit rule is explicitly scoped to the system-managed `created_at`/`updated_at`. The implementation was the outlier, even rewriting client-supplied `scheduled_start` into `.000Z`. STEP 2: tests faithful. STEP 3: implementation fixed as above; envelope `api_request_timestamp` correctly retains three fractional digits per §2.2.

## Step 8: Finalize PRD — 2026-08-14T19:41:00.000Z

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1811_unemployment_insurance_claims_response/workspace/PRD_FINALIZED.md`.

## Summary

**Line counts / delta:** PRD.md = 379 lines, PRD_FINALIZED.md = 381 lines (+2 lines, +0.53%). One inserted sentence (plus its blank separator line); all other prose verbatim.

**Changes (one total):**
- **§2.4 — insert** — Added a closing sentence pinning that every datetime-valued resource field other than `created_at`/`updated_at` renders as ISO 8601 UTC pinned to whole seconds with no fractional component (e.g., `2026-08-13T17:00:00Z`), and that on resources the three-fractional-digit form applies only to `created_at`/`updated_at` — `implementation/services/core.py:41` (the `fmt_ts`/`fmt_plain` split in `serialize()`), `implementation/util.py:33-48`.

This was the only Step 7 item (one root cause, two impl files: `util.py` added `fmt_plain()`; `core.py` applied it in `serialize()`). It was a genuine PRD silence: §2.4 pinned three fractional digits only for `created_at`/`updated_at` and §2.5/§2.6 used plain-seconds literals, but no affirmative rule covered business datetime rendering — the gap the original implementation filled by generalizing `.000Z` to every datetime. No other Step 7 items existed (no test deletions, no test-suite/test-helper fixes).

**Per-edit pre-edit search log (NO-NEW-MISMATCH):**
- **(a) Subject:** wire rendering (serialization format) of datetime-valued fields on resources.
- **(b) Impl paths enumerated and read/grepped:**
  - `implementation/services/core.py:32-44` — `serialize()`, the single resource-serialization path; `created_at`/`updated_at` → `fmt_ts` (3 fractional digits), all other datetimes → `fmt_plain` (whole seconds).
  - `implementation/util.py:33-48` — `fmt_ts` (`...:SS.mmmZ`) and `fmt_plain` (`...:SSZ`) definitions.
  - `implementation/response.py:16-20` — envelope `api_request_timestamp` uses `fmt_ts`; it is not a resource field and is already pinned by §2.2.
  - `implementation/routes/clock.py:14-22` + `implementation/db.py:26-29` — `POST /_clock/set_current_utc` reports `current_utc` by echoing the raw client-supplied `to_iso8601` string verbatim (initial value `"2026-08-01T00:00:00Z"`); not a resource field and not touched by Step 7.
  - All 14 route modules — 75 `serialize(`/`list_view` call sites (grep-verified); no route renders a datetime outside `serialize()`; no `isoformat`/`strftime` anywhere outside `util.py`.
  - Datetime-carrying resource fields verified via `as_dt`/`parse_dt` grep: claims (`notice_received_at`, `benefit_year_begin`, computed `response_due_at`, response `filed_at`), separations (`last_day_worked`), determinations (`mailed_at`, computed `appeal_due_at`), hearings (`scheduled_start`, `scheduled_end`), witnesses (`availability_start`, `availability_end`), evidence (`doc_date`), statements (`issued_at`, computed `protest_due_at`), appeals/protests (`filed_at`), TPA engagements (`effective_from`, `effective_to`); `services/deadlines.py:24-26` pins computed deadlines to 17:00:00 UTC as `datetime` objects. All render through `serialize()` → plain seconds.
- **(c) Wording adjustment:** Yes — an early draft ended "...the three-fractional-digit form applies only to `created_at` and `updated_at`," which as a universal claim would have contradicted §2.2 (envelope `api_request_timestamp` legitimately keeps three fractional digits) and risked over-claiming about non-resource payloads like the clock endpoint's `current_utc` (raw-string echo). The committed wording scopes both clauses with "carried on a resource" / "on resources," making it consistent with every enumerated path, including those Step 7 never exercised.

## Step 9: Complete PRD — 2026-08-14T20:02:00.000Z

All edits are complete and coherent. Here is the summary.

## Summary

**Source vs. output:** `PRD_FINALIZED.md` (381 lines / 61,184 chars) → `PRD_COMPLETED.md` (382 lines / 66,362 chars), char-delta **+5,178**. 21 in-place edits, all inline paragraph inserts/revisions; one row added to the existing §5 table; no new sections.

**Counts:** 7 mismatch-revisions, 25 ambiguity-pins.

### Mismatch-revisions (PRD described different behavior)
- §3.1 (TPA scope) — revise — mismatch — draft-time and submit-time authority accept `ACTIVE` **or `REINSTATED`** (PRD said only `ACTIVE`); also pins draft-time cross-parent error, no window consult at draft, and the unnamed-engagement fallback — `routes/tpa.py:23`, `routes/responses.py:40-74, 236-241`
- §3.1 (termination) — revise — mismatch — open-work guard keyed on a `DRAFT` response bound via `filed_by_tpa_id` on a `RESPONSE_IN_PROGRESS` claim (PRD keyed on `response_channel`, which is null pre-submission) — `routes/tpa.py:130-137`
- §3.4 (submission) — revise — mismatch — TPA engagement must be `ACTIVE` or `REINSTATED` and in-window — `routes/responses.py:233-241`
- §3.4 (draft payload) — revise — mismatch — `separation_reason_code` must *equal* the separation's recorded reason (PRD said "equal or narrow"), else `ERR_INVALID_REQUEST` — `routes/responses.py:119-126`
- §3.5 (appeal withdrawal) — revise — mismatch — hearings in `READY` are also closed, not just `SCHEDULED`/`PREP_IN_PROGRESS` — `routes/appeals.py:121-124`
- §3.6 (variance) — revise — mismatch — `total_charged_cents` syncs to the sum of lines not `REVERSED`/`WAIVED` (`PROTESTED` lines remain included), not to the audited total — `routes/charges.py:65-68`
- §3.6 (reconcile) — revise — mismatch — supersedes *all* of the employer's models (any year, `DRAFT` and `FINALIZED`) and re-evaluates `current_tax_rate_bps` immediately (PRD said "current model year… recomputed on next read") — `routes/charges.py:243-245`

### Ambiguity-pins (PRD silent)
- §2.3 — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; out-of-range values clamped — `response.py:47-64`
- §2.3 — creation-timestamp ties broken by creation sequence — `services/core.py:54-57`
- §2.5 — clock-set accepts any parseable timestamp (backward moves allowed) and echoes the supplied value as `current_utc` — `routes/clock.py:14-22`
- §2.5 — envelope `api_request_timestamp` and resource `created_at`/`updated_at` read the logical clock — `response.py:16-20`, `services/core.py:15-23`
- §2.8 tier 10 — segregation-of-duties rejection surfaces concretely as `ERR_AUTHORITY_VIOLATION` — `routes/responses.py:270-277`
- §3.1 — duplicate `fein` → `ERR_DUPLICATE_ACTIVE_RECORD` — `routes/employers.py:34-36`
- §3.1 — duplicate `state_code` → `ERR_DUPLICATE_ACTIVE_RECORD` — `routes/state_rules.py:44-45`
- §3.1 — body naming an unregistered `state_code` → `ERR_NOT_FOUND` — `routes/claims.py:70-73`, `routes/charges.py:98-100`
- §3.1 — direct suspend possible from `ACTIVE`/`REINSTATED`, else `ERR_INVALID_STATE` — `routes/tpa.py:101-102`
- §3.1 — reinstatement sets `oversight_status` to `REINSTATED` — `routes/tpa.py:118`
- §3.1 — termination from other statuses → `ERR_INVALID_STATE` — `routes/tpa.py:128-129`
- §3.2 — coding confirm permitted from any confidence value — `routes/separations.py:80`
- §3.3 — past-deadline claims read `EXPEDITED`; posture also recomputed at submission, withdrawal, closure — `routes/claims.py:43-50, 185, 209`, `routes/responses.py:262`
- §3.4 — drafting an amendment immediately supersedes the still-`DRAFT` response it names — `routes/responses.py:147-150`
- §3.4 — assembly score computed over all evidence on the claim, whatever response each document references — `services/scoring.py:39-50`
- §3.4 — `completeness_score` recomputed at submission over then-current evidence — `routes/responses.py:244`
- §3.4 — ack from any status other than `RESPONSE_SUBMITTED`/`LATE_RESPONSE` → `ERR_INVALID_STATE`; late flag surfaced as `late_flagged: true` on the claim — `routes/clock.py:33-45`
- §3.4 — SoD violation rejected with `ERR_AUTHORITY_VIOLATION` (403) — `routes/responses.py:270-277`
- §3.5 — either authorized role may file either appellant — `routes/appeals.py:44-51`
- §3.5 — referee buffer intersection is closed (touching intervals conflict) — `routes/hearings.py:32-44`
- §3.5 — witnesses addable while `SCHEDULED`/`PREP_IN_PROGRESS`/`READY` (`HELD`/`CLOSED` → `ERR_INVALID_STATE`); adding to a `READY` hearing returns it to `PREP_IN_PROGRESS` — `routes/hearings.py:134-158`
- §3.5 — prep advance at top rung → `ERR_INVALID_STATE` — `routes/hearings.py:173-178`
- §3.5 — continuance allowed from `SCHEDULED`/`PREP_IN_PROGRESS`/`READY` (else `ERR_INVALID_STATE`); re-promotes to `READY` immediately if all witnesses `READY` — `routes/hearings.py:193-212`
- §3.5 — REVERSE decision leaves the claim in `HEARING_PENDING` — `routes/appeals.py:172-183`
- §3.5 — re-appeal `round_number` = highest `REMANDED` round on the claim + 1 — `routes/appeals.py:29-40`
- §3.5/§3.6 — closure requires the *latest-recorded* determination `FINAL`; posting a charge line requires employer match (`ERR_CROSS_PARENT_REFERENCE`) but enforces no determination-outcome gate — `routes/claims.py:200-203`, `routes/charges.py:155-168`
- §3.6 — statement carries five named audit-aggregate fields, zero at issuance; variance also recomputes on line posting — `routes/charges.py:102-115, 183`
- §3.6 — audit completion requires `UNDER_AUDIT` (else `ERR_INVALID_STATE`); late protest keeps `evidence_strength` 0 with line/statement untouched; "open" protest defined as `FILED`/`UNDER_REVIEW`; sustain/deny/withdraw state failures → `ERR_INVALID_STATE`; evidence-score tie extended by creation sequence — `routes/charges.py:48, 211-212, 307-311, 375-376, 401-402, 426-427`, `services/scoring.py:53-64`
- §3.7 — snapshot-hash inputs enumerated (variant, charges, reserve, payroll, posture); zero-payroll ratio rule (0 if numerator 0, else above all ceilings); rate refresh always under the employer's own `merit_rating_method`; rating summary carries exactly the four documented fields — `services/rating.py:43-46, 69-89`, `routes/employers.py:106-115`
- §5 — catalogue row added: `ERR_AUTHORITY_VIOLATION` | 403 Forbidden — `errors.py:60`

The file is at `/home/ubuntu/github/CodingPRD/tasks/task_1811_unemployment_insurance_claims_response/workspace/PRD_COMPLETED.md`.
