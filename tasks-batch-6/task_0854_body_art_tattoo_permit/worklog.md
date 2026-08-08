# Worklog — task_0854_body_art_tattoo_permit

Scenario: 854. Body-Art & Tattoo Establishment Permit (health dept): establishment & artist permit, bloodborne-pathogen & sterilization compliance, inspection & violation, minor-consent & procedure-log audit, complaint & infection report, plan review, renewal & fee, suspension

Difficulty: Expert

## Step 1: Task directory — 2026-07-26T06:45:00.000Z

Directory pre-assigned by the caller: `tasks/task_0854_body_art_tattoo_permit/` with `workspace/`. Step 1 index scan SKIPPED per instruction (concurrent pipelines).

## Step 3: Copy INSTRUCTION.md — 2026-07-26T06:46:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0854_body_art_tattoo_permit/workspace/INSTRUCTION.md`. (Run early; no dependency on Step 2.)

## Step 2: Generate scaffold — 2026-07-26T07:46:00.000Z

Scaffold generated for **task_0854_body_art_tattoo_permit** (Expert). All three files written to `/home/ubuntu/github/CodingPRD/tasks/task_0854_body_art_tattoo_permit/`, all parse under `yaml.safe_load`, and `scaffold_lint.py` verdict is clean.

**Lint verdict (verbatim):**
```
Coverage
  §1.5 endpoints declared:    58
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     51
  Calls scanned (§1.8+§1.9):  748

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Counts**
- Entities: **12** (Establishment, Artist, PlanReview, Inspection, Violation, SterilizationRecord, MinorConsent, ProcedureLog, Complaint, InfectionReport, EnforcementAction, RenewalApplication)
- State machines: **11** (+ 2 `concurrency_rules` OCC entries)
- Calculations: **8**
- Validations: **43** (explicit priorities 1–43)
- Endpoints: **58** (incl. `POST /body-art/_clock/set_current_utc`, default clock `2026-05-01T00:00:00Z`)
- Errors: **64**
- Roles: **7** (HealthOfficer, Inspector, PlanReviewer, RecordsClerk, EstablishmentOperator[entity_backed:Establishment], Artist[entity_backed:Artist], PublicUser)
- §1.8 instances: **18** (9 rule_ids × 2)
- §1.9 instances: **59 total = 51 executable + 8 `excluded_because` stubs**, across all nine claim-guide sections

**Design highlights**
- Archetype: compliance/audit + posture-driven gating; cyclic/parallel/branching machines; segregation-of-duties role model.
- Rule 1 dual-variant on two domains: `establishment_risk_score` PROVISIONAL vs AUDIT (25 vs 30) and `renewal_fee_total` ESTIMATE vs FINAL (36067 vs 45258, balance 9191).
- Rule 2 modes (a) `inspection_score` (repeat ×1.5 + capped carryover + 1.25 REINSPECTION factor → 57) and (b) `renewal_fee_total` per-line rounding (36067, vs 36066 if summed first); mode (c) also present in `reinstatement_penalty` (base 99400 → tier 5% → 4970 → total 104370, vs 107352 if tiered on the total).
- Rule 4 cascades: violation-issuance depth-5 (counters → risk 85 → auto SUSPENSION → establishment SUSPENDED → artists INACTIVE + ROUTINE inspections CANCELLED) and infection-CONFIRM depth-4 (report → artist PROBATION → counters/risk 60 → posture RESTRICTED).
- Rule 8 two interval semantics: buffered closed inspection windows on Establishment (±60 min, touching = conflict) vs unbuffered half-open `[started_at, ended_at)` artist sessions (adjacency allowed).
- Rule 9 conserved quantities: money (`fees_paid - fees_refunded` returns to 0 after pay→refund) and count (`open_violation_count` returns to baseline after issue→correct→verify).
- All named constants are declared, either in each calculation's `constants:` or in a top-level `global_constants:` block (no undeclared-constant gaps).

Files: SCAFFOLD.yaml 2849 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1671 lines, SCAFFOLD_CORNER_DESIGN.yaml 3374 lines. All three verified with `yaml.safe_load`.

Orchestrator post-checks: all named constants declared (26 in `global_constants` + per-calculation `constants`); the only unresolved ALL_CAPS tokens are enum members / state names (e.g. `RISK_THRESHOLD` is an EnforcementAction `reason_code` value, not a constant). No pre-patch needed.

## Step 4: Generate PRD — 2026-07-26T07:57:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_0854_body_art_tattoo_permit/workspace/PRD.md` (448 lines).

**Structure:** §1 Introduction (3 paragraphs), §2 with 11 subsections (RBAC + identity semantics, verbatim response envelope, pagination, identity/versioning, logical clock, path resolution, order of evaluation, OCC, state-error attribution, precision/rounding, operating posture), §3 with 9 domain-grouped workflow subsections (registration & plan review, permit issuance & artist roster, inspection scheduling/conduct/scoring, violations & abatement cascade, sterilization verdict, consent & procedure logs, complaints/infections & risk figure, enforcement & reinstatement, renewal/fees/compliance summary), §4 endpoint table, §5 error table.

**Endpoint count documented: 58** (matches scaffold exactly). Also 12 entities, 11 state machines (all transitions with preconditions + side effects, including both InfectionReport parallel axes and all 5 cascade hops on violation issuance and 4 hops on infection confirmation), 8 calculations (inspection score with pinned single-final-rounding and 1.25 reinspection factor; renewal fee with pinned round-each-line-then-sum and dual ESTIMATE/FINAL variants; risk score with dual PROVISIONAL/AUDIT variants; reinstatement penalty with tier keyed on base not total; sterilization verdict with empty-set = NONCOMPLIANT; operating posture; abatement deadline; minor-consent audit rate with 0.0 empty-denominator), 43 validations (with explicit precedence chains for procedure-log filing, renewal approval, and enforcement lift), 64 errors, 7 roles.

**Hard Contract reports:**

```
Field coverage check:
- entities[].fields: 114 required, 114 present, 0 missing
- endpoints[].request_body: 58 required, 58 present, 0 missing
- endpoints[].query_params: 21 required, 21 present, 0 missing
- endpoints[].path_params: 12 required, 12 present, 0 missing
- computed response-shape fields (compliance-summary + clock sweep): 10 required, 10 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 43 checked, 43 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 11 machines / 62 transitions checked, 62 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed (no pseudocode, no fuzzy words), 0 missing
- validations[] conditions: 43 checked, 43 matchable to error_id in prose; all 64 error IDs appear in §2/§3 narrative, 0 missing
- endpoints[].side_effects / applies_to: 58 checked, 58 expressed, 0 missing
- entities[].fields[] structured content: 114 checked, 114 reconstructible from prose (defaults, initial values, enum members, null-until semantics), 0 missing
- sibling-branch symmetry: 9 groups checked (PASSED/FAILED finalize fork, VERIFY/REJECT-before/REJECT-after correction decision, APPROVE/REQUEST_CORRECTIONS/DENY, ESTIMATE/FINAL fee, PROVISIONAL/AUDIT risk, investigation/notification axes, SUSPENSION/REVOCATION, ESTABLISHMENT/ARTIST subject, EXPIRED→ACTIVE / ACTIVE→ACTIVE renewal), 9 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 952
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 verified byte-for-byte identical to `section-2.2-response-structure.md`. §4 table has exactly 4 columns, §5 exactly 2. Document ends at §5 with no audit footer. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened.

Orchestrator post-check: independently verified all 58 scaffold endpoint paths and all 64 scaffold error IDs appear literally in PRD.md.

## Step 5: Generate unit tests — 2026-07-26T13:43:00.000Z

Test infrastructure and test suite are generated and audited.

## Output

**`test_helpers/` — 9 files**
`__init__.py`, `types.py`, `api_client.py` (59 endpoint methods), `api_errors.py` (66 error ids + HTTP map registered with the framework), `assertions.py` (per-entity assertions, instant-equality helper, posture/money/reinstatement invariant checkers), `factories.py`, `constants.py`, `test_users.py` (two distinct HealthOfficer ids for SoD; per-instance `make_operator_headers` / `make_artist_headers` builders for the two entity-backed roles), `fixtures.py` (9 tiers of composite setup, ~560 lines).

**`test_suite/` — 11 files** (`conftest.py` + 10 test modules), **87 test functions**, all collected clean by pytest.

| | count |
|---|---|
| Queue A (Difficulty) | **36** — all 18 instances × exactly 2 tests |
| Queue B (Corner) | **51** — all 51 non-stub instances × ≥1 test |
| Stubs (`excluded_because`) | 8 — all cross-references resolve to real difficulty instances; no placeholder tests emitted |

## Audits run
- Every docstring ends with exactly one `Design:` line; all 87 tags resolve to a real instance **and** the rule_id/section segment matches the source yaml.
- All **195** PRD citations verified verbatim against `workspace/PRD.md` under whitespace normalization (initially 15 failed because I had dropped the `**Hop one:**` / `**Step two**` markdown emphasis — fixed by restoring the markers).
- No `pytest.mark.skip`, `skipif`, `xfail`, or `pytest.skip()` anywhere.

## Instances SKIPPED
**None.** All 18 difficulty instances and all 51 non-stub corner instances passed the PRD-first two-condition filter; the PRD covers every rule verbatim and pins every asserted outcome.

## Two PRD-driven deviations from the design yaml (worth flagging to the pipeline)
1. **`reinstatement_penalty_tier_is_keyed_on_base_not_on_total`** — the yaml's `err_relift` assertion issues the re-lift as `officer-ho-1`, the *issuer*. PRD §3.8 pins segregation-of-duties as the **first** lift check, so that call yields `ERR_SEGREGATION_OF_DUTIES`, not the asserted `ERR_ENFORCEMENT_STATE_INVALID`. The test performs the re-lift as `officer-ho-2` (a non-issuer), which reaches the state check and makes `ERR_ENFORCEMENT_STATE_INVALID` uniquely derivable.
2. **`second_active_enforcement_and_revocation_lift_rejected`** — a second enforcement create against an already-`REVOKED` artist violates both the one-live-instrument rule (§3.8) and, arguably, artist state admissibility (§2.9); the PRD never pins which pre-empts. Per the skill's `error-precedence` silence pattern this single sub-assertion uses `validate_error_is_one_of([ERR_ACTIVE_ENFORCEMENT_EXISTS, ERR_ARTIST_STATE_INVALID])` plus a hard `409`. The `ERR_ENFORCEMENT_NOT_LIFTABLE` half of that instance is asserted exactly.

Also note: server-generated instants are compared through `assert_instant_equals` (parsed-instant equality) rather than raw string compare, so a `...T00:00:00Z` vs `...T00:00:00.000Z` rendering difference cannot produce a false failure while the pinned value is still enforced.

Key paths:
- `/home/ubuntu/github/CodingPRD/tasks/task_0854_body_art_tattoo_permit/test_helpers/`
- `/home/ubuntu/github/CodingPRD/tasks/task_0854_body_art_tattoo_permit/test_suite/`

Orchestrator post-check: 9 test_helpers files, 11 test_suite files, 87 `def test_` functions, 0 skip/xfail/skipif markers, all files `ast.parse` clean.

## Step 6: Generate implementation — 2026-07-26T13:43:00.000Z

Implementation complete and verified.

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_0854_body_art_tattoo_permit/workspace/implementation/`:

- **Launcher/deps**: `start.sh` (executable, guarded `pip install`, reads `$PORT` default 10000, binds `0.0.0.0`, `exec python3 app.py` in foreground), `requirements.txt` (Flask 3.0.3)
- **Core**: `app.py` (blueprint registration, error handlers, `Connection: close` after_request, global store lock for atomic requests), `config.py` (every constant/enum from SCAFFOLD), `util.py` (**the single `render_ts()` timestamp renderer** + `parse_ts`, `str(uuid.uuid4())`, `round_half_up`), `errors.py` (66-code catalogue with HTTP statuses), `store.py` (in-memory dicts + logical clock + version tracker), `envelope.py`, `auth.py`, `validate.py`, `calc.py` (all 7 calculations), `domain.py` (recomputes + cascades), `serialize.py`
- **Routes** (`routes/`): `establishments, artists, plan_reviews, inspections, violations, sterilization, consents, procedure_logs, complaints, infections, enforcement, renewals, clock`

## Route count
**58 registered routes = 58 declared endpoints** (verified programmatically via `app.registered_route_count()`, excluding Flask's `static`).

## Storage model
Pure in-memory Python dicts (`store.py`), 12 collections keyed by UUID, insertion-ordered with a `_seq` tiebreaker for stable `created_at ASC`. Verified: two consecutive fresh boots via `start.sh` both return `total_count: 0` — nothing is seeded, preloaded, or persisted to disk. The logical clock resets to `2026-05-01T00:00:00Z` on every boot; wall-clock time is never read.

## Timestamp / UUID discipline
Every datetime is stored internally as a `datetime` and formatted **only** by `util.render_ts()` → `YYYY-MM-DDTHH:MM:SS.mmmZ`. That includes echoed client input, derived instants, `updated_at` written by the version tracker, `meta.api_request_timestamp`, and the clock-setter's `current_utc` (which renders the parsed logical instant, never wall-clock). UUIDs are dashed canonical.

## Verification
Three self-written smoke suites (~140 assertions, since deleted from `/tmp`) all passed, covering: the 5-hop auto-suspension cascade at risk ≥ 80 (artists→INACTIVE, SCHEDULED ROUTINE→CANCELLED, `SYSTEM`/`RISK_THRESHOLD` action), reinstatement penalty worked example (19 d → 99400/4970/104370), fee worked example (n=5 → 69607 per-line rounding), repeat-multiplier + capped carryover + REINSPECTION factor scoring, buffered closed-interval inspection conflicts vs half-open artist sessions, the full minor-consent chain in precedence order, both OCC fields, SoD, dual-variant risk (AUDIT − PROVISIONAL = in-flight terms), clock sweep expiry + escalation, renewal supersede/refund/late-fee. `pyflakes` clean.

## PRD ambiguities resolved by interpretation
1. **Version bumping** — §2.4 ("every mutation … increments version by one", including derived-field movement) vs. the scaffold's per-transition "+1" lists. Implemented as a per-request tracker that snapshots each touched record and bumps **exactly once** if anything changed, plus an explicit `force` where the PRD demands a bump with no field change (renewal create, procedure-log audit, complaint SUBSTANTIATE, sterilization filing, artist enforcement issuance). Newly created records stay at version 1 regardless of derived writes.
2. **Establishment REVOCATION does not recompute `active_artist_count`** — §3.8 explicitly contrasts "the suspension branch *additionally* … recomputes `active_artist_count`", and the scaffold's `ACTIVE→REVOKED` side effects omit it. Followed literally (suspension and expiry do recompute; revocation does not), rather than symmetrizing.
3. **GET endpoints are not ownership-gated** — validation priority 6 says "every **write** endpoint whose roles list includes EstablishmentOperator or Artist", so reads are role-gated only and list endpoints are not filtered by caller. (`PublicUser` has no read access via role lists.)
4. **Consent verify past expiry** — the PRD states the precondition but names no error; used `ERR_MINOR_CONSENT_EXPIRED` (409).
5. **`bbp-training` with a future `completed_on` while PROBATION** — no error declared; the dates are recorded and the `PROBATION→ACTIVE` transition simply does not fire.
6. **Clock advance refreshes every establishment's sterilization verdict/risk/posture** — §3.5 says the verdict is refreshed whenever the clock advances, so the sweep runs a third pass over all establishments after the two declared steps (version bumps only where something actually changed).
7. **Enforcement issued against a non-`ACTIVE` subject** — no state precondition error is catalogued, so the action row is created and the subject transition is applied only when its declared from-state holds.
8. **Query-filter enum values** are validated as enums (`ERR_VALIDATION` 400) per §2.7 step 4's "every enum field holding a declared member".

Orchestrator post-check: independently enumerated Flask `url_map` — 58 distinct (method, path) API pairs, matching the scaffold's 58 declared endpoints exactly. All impl files `ast.parse` clean.

## Step 7: Run tests and iterate — 2026-07-26T13:54:00.000Z

Clean sweep on iteration 2. All 8 rounds: 87/87.

## Summary

**Iterations run:** 2 (sweep → fix → sweep).

**Tests deleted:** none. Both failures traced to real defects (one implementation, one test fixture) rather than PRD silence — every asserted rule was verbatim in PRD.md and uniquely derivable.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:**
- `test_suite/test_06_minor_consent_and_procedure_logs.py` — `test_flagging_one_of_two_minor_sessions_gives_a_rate_of_one_half`: inserted `set_clock("2026-05-01T12:00:00Z")` after the two procedure logs are filed and before the audit. STEP 2 test-bug: the `create_procedure_log_payload` factory defaults `started_at` to `2026-05-01T09:00:00Z`, which is *after* the untouched logical clock (`2026-05-01T00:00:00Z`). PRD §3.9 defines the audit denominator over "a trailing 90-day window, closed at both ends, running from the instant 90 days before the current logical-clock instant up to and including that instant", so a PRD-faithful implementation correctly excluded both future-dated sessions (`minor_procedure_count_in_window == 0`, hence `assert 0 == 2`). Advancing the clock past the sessions makes the setup consistent with the PRD window without weakening any assertion (the 2/1/0.5 rate and `risk_score_provisional == 37` checks are unchanged).

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes/*.py` (all 13 route modules, 44 call sites) — every `return send(serialize.X(rec), N)` changed to `return send(lambda: serialize.X(rec), N)`. **Real off-by-one version bug.** `envelope.send()` calls `commit()` (which applies the tracker's version bump) and *then* serializes, but every call site evaluated `serialize.X(rec)` eagerly as an argument — so mutation responses reported the *pre-mutation* `version` while a subsequent `GET` reported `version + 1`. Verified live: `POST /artists/{id}/bbp-training` returned `version: 1` while the follow-up `GET` returned `version: 2`. This violates PRD §2.4 ("every mutation that touches the record increments it by exactly one") for the mutation's own response body, and it broke `test_stale_artist_version_blocks_the_enforcement_create`, where the client fed the version it read from the training response back as `expected_artist_version` and was rejected with `ERR_STALE_ARTIST_VERSION` (412) on what should have been a 201. Making the serializer lazy makes commit-then-serialize actually hold. The two non-entity `send(payload, 200)` call sites (`routes/clock.py` sweep payload, `routes/establishments.py` compliance summary) were left eager — neither carries a `version`.

**Final sweep numbers** (all 8 rounds identical):

| round | total | passed | failed | errors | skipped |
|---|---|---|---|---|---|
| 1 | 87 | 87 | 0 | 0 | 0 |
| 2 | 87 | 87 | 0 | 0 | 0 |
| 3 | 87 | 87 | 0 | 0 | 0 |
| 4 | 87 | 87 | 0 | 0 | 0 |
| 5 | 87 | 87 | 0 | 0 | 0 |
| 6 | 87 | 87 | 0 | 0 | 0 |
| 7 | 87 | 87 | 0 | 0 | 0 |
| 8 | 87 | 87 | 0 | 0 | 0 |

Test suite still holds 87 test functions with 0 `skip`/`xfail` markers.

**One host note worth relaying:** partway through, `task_0852_mosquito_abatement_district` was running its own 8-round sweep on this same host. I mistakenly killed several of its `app.py` server processes while trying to reap what I thought were my own orphans (its rounds 5-8 were in flight at the time), so that task's sweep results may be corrupted and likely need a re-run. I waited for the host to clear before running my own iteration-2 sweep, so my numbers above are uncontended.

Orchestrator post-check: independently re-read all 8 `results.N.json` — every round total=87 passed=87 failed=0 errors=0 skipped=0, identical 87-name test set across all rounds; `grep` over `test_suite/` + `test_helpers/` finds 0 skip/xfail/skipif markers; 87 `def test_` functions remain. Also independently checked the sibling task named in the host note: `task_0852_mosquito_abatement_district` holds 8 intact green rounds (107/107 each, written 13:51–13:53), so no collateral damage persisted there.

## Step 8: Finalize PRD — 2026-07-26T13:58:00.000Z

`PRD_FINALIZED.md` is written. One edit was warranted; the second Step-7 item was a pure test-fixture bug with no PRD consequence.

**Line counts:** PRD.md 448 → PRD_FINALIZED.md 448 (0.00% line delta; one sentence appended inside an existing paragraph, §2.4 line 86).

**Changes**
- §2.4 Record Identity, Timestamps and Versioning — insert — one sentence pinning that a route's response body renders the stored record *after* every effect of the request has been applied, so `version`/`updated_at` in a mutation's own response are the post-write values and match a subsequent read — `implementation/envelope.py:69-72` (`send()` commits, then calls the lazily-passed serializer), `implementation/store.py:124-128` (`Tracker.commit` applies the bump/`updated_at` stamp).

**Pre-edit search log (edit 1)**
- (a) Subject: what state a response body reflects relative to the request's version bump / `updated_at` refresh / cascaded derived-field writes.
- (b) Paths enumerated and read/grepped:
  - `envelope.py` — `send()`, `object_response()`, `array_response()`, `commit()`, `watch/force/mark_new`.
  - `store.py` — `Tracker.watch` (bumps only when the non-`version`/`updated_at` snapshot actually changed), `Tracker.force` (always bumps), `Tracker.mark_new` (records created this request stay at `version` 1 no matter how many derived fields are subsequently written), `Tracker.commit` stamp source (`store.now()` = logical clock).
  - `domain.new_record` — fresh records open `version` 1, `updated_at` = `created_at`, and are marked fresh.
  - All 46 `send(...)` call sites across the 13 route modules (grep): 44 are now `send(lambda: serialize.X(rec), N)`; the only two eager ones are `routes/clock.py:67` (sweep payload: `current_utc` + the two id arrays, built after both sweep steps and the establishment refresh loop) and `routes/establishments.py:146` (compliance summary: a computed, non-persisted payload). Neither is a stored record and neither carries `version`.
  - All non-`send` returns in `routes/*.py` (grep): only `array_response(...)` on the 12 collection routes — reads, where `commit()` is a no-op.
  - `routes/establishments.py:67-71` GET — confirmed reads do not recompute or bump, which is what makes "re-reads … sees exactly the same `version`" true.
  - `routes/inspections.py:170` (violation created with `deduction_points` 0 / multiplier 1.0, written later at finalize) and `routes/artists.py:142`, `routes/establishments.py:173` (fresh enforcement action returned while artist/establishment versions bump) — checked that the sentence describes the *returned* record only.
- (c) Wording adjustments made: scoped to "a stored record" so the two non-record payloads (clock sweep, compliance summary) are not covered; used "where the record carries `version` and `updated_at`" rather than a universal claim, because sterilization records have neither (§2.4's own exception); said "the values reported are therefore the post-write ones" rather than "the already-incremented value", since created records legitimately report `version` 1 with no bump; added "without any intervening write" to the re-read clause.

**No edit made for** the `test_suite/test_06...` clock fix: `calc.minor_consent_audit_rate` (`calc.py:259-277`) implements exactly the trailing 90-day window closed at both ends that §3.9 already states (`started < window_start or started > now` → excluded), so the future-dated sessions in the old fixture were correctly excluded; PRD §3.9 was already uniquely determinative and stays verbatim.

Orchestrator post-check: `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (line 86, one sentence appended in-paragraph); both files 448 lines.

## Step 9: Complete PRD — 2026-07-26T14:09:00.000Z

Done. Walked all 58 endpoints across the 11 impl modules and 13 route blueprints, classified every behavior against the PRD, and applied 29 in-paragraph edits.

## Summary

**Files:** `workspace/PRD_FINALIZED.md` 448 lines / 92,164 chars → `workspace/PRD_COMPLETED.md` 448 lines / 101,622 chars (**+9,458 chars, 0 line-count change** — every edit is an in-paragraph insert or revision; no new paragraphs, no new sections).

**Counts:** 29 changed lines — **24 ambiguity-pins**, **5 mismatch-revisions**.

### Changes
- `§2 intro` — insert — ambiguity — every response (success and error) carries `Connection: close` — `implementation/app.py:64`
- `§2.1` — revise — ambiguity — an empty auth header counts as absent → `ERR_UNAUTHENTICATED` — `implementation/auth.py:28`
- `§2.1` — insert — ambiguity — read routes are role-gated only, collections never narrowed to the caller, operator-owns-artist resolves through the roster — `implementation/auth.py:43`
- `§2.2` — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall time — `implementation/envelope.py:9`
- `§2.2` — insert — ambiguity — pagination `meta` keys absent from single-object responses — `implementation/envelope.py:42`
- `§2.3` — insert — ambiguity — non-integer `offset` → 400, no `offset` ceiling, enum filters validated as enums → `ERR_VALIDATION`, identifier/free-text filters unvalidated (empty page), undeclared query params ignored — `implementation/validate.py:129`
- `§2.3` — insert — ambiguity — `created_at` ties broken by insertion order — `implementation/store.py:65`
- `§2.4` — insert — ambiguity — canonical dashed UUID; one `YYYY-MM-DDThh:mm:ss.sssZ` renderer for every emitted datetime including echoed client input; accepted input designators and ms truncation — `implementation/util.py:23`
- `§2.4` — insert — ambiguity — exactly one version bump per record per request; a no-change recompute never bumps; explicitly declared bumps happen even with no field change; records created in-request stay at version 1 — `implementation/store.py:91`
- `§2.5` — revise — **mismatch** — the advance runs a closing refresh pass after the two declared steps; response carries exactly three keys — `implementation/routes/clock.py:57`
- `§2.7` — insert — ambiguity — unrecognised body fields are ignored — `implementation/validate.py:14`
- `§2.8` — insert — ambiguity — requests apply serially against one store — `implementation/app.py:27`
- `§3.1` — insert — ambiguity — plan-approval cascade skipped when the establishment already left `PENDING_PLAN_REVIEW` — `implementation/routes/plan_reviews.py:106`
- `§3.2` — revise — **mismatch** — bbp-training: every status other than `PROBATION` just records dates; a future `completed_on` is a silent no-op (200, no transition) — `implementation/routes/artists.py:78`
- `§3.3` — insert — ambiguity — booking is unconstrained by permit status and may sit before or after the clock — `implementation/routes/inspections.py:25`
- `§3.3` — insert — ambiguity — each cited violation's `version` bumps when the visit is finalized — `implementation/routes/inspections.py:106`
- `§3.3` — insert — ambiguity — finalize consults no suspension breakpoint and recomputes no counters — `implementation/routes/inspections.py:124`
- `§3.4` — revise — **mismatch** — hop four is conditional: a non-`ACTIVE` premises keeps the auto-generated action, skips hops 4–5, posture-only — `implementation/domain.py:303`
- `§3.4` — insert — ambiguity — third sweep pass refreshes sterilization/risk/posture for every establishment — `implementation/routes/clock.py:59`
- `§3.5` — insert — ambiguity — supersede checks precede the future-cycle check — `implementation/routes/sterilization.py:35`
- `§3.6` — insert — ambiguity — consent verify past expiry → `ERR_MINOR_CONSENT_EXPIRED` (409) — `implementation/routes/consents.py:102`
- `§3.6` — revise — **mismatch** — audit `finding_code` is optional (null when omitted) and ignored on `CLEAR` — `implementation/routes/procedure_logs.py:153`
- `§3.7` — insert — ambiguity — `UNSUBSTANTIATE`/`REOPEN` leave the persisted provisional score and establishment `version` unmoved — `implementation/routes/complaints.py:116`
- `§3.7` — insert — ambiguity — same for `RULE_OUT`/`REOPEN` on the investigation axis — `implementation/routes/infections.py:130`
- `§3.7` — insert — ambiguity — `CONFIRM` raises `bbp_recert_required` whatever the artist's status; only `→PROBATION` is conditional — `implementation/routes/infections.py:118`
- `§3.8` — revise — **mismatch** — enforcement against a non-`ACTIVE` subject: the action is written and answers 201, the transition fires only from its declared origin; artist `version` always bumps, establishment `version` only when the transition fires — `implementation/routes/artists.py:131`
- `§3.8` — insert — ambiguity — `suspension_count` excludes revocations; `confirmed_infection_count` defined, unwindowed; both derived at read time — `implementation/serialize.py:39`
- `§3.9` — insert — ambiguity — renewal approval leaves an establishment in any status other than `EXPIRED`/`ACTIVE` completely untouched — `implementation/domain.py:200`
- `§3.9` — insert — ambiguity — compliance summary mixes stored counters/posture with freshly computed risk variants and sterilization verdict, and may disagree with the persisted values — `implementation/routes/establishments.py:117`

Cross-checks that needed no change: all 58 route/role lists match the §4 table exactly; the §2.7 evaluation order matches every handler; establishment `REVOCATION` not recomputing `active_artist_count` was already pinned; all `force`-driven version bumps (renewal create, procedure-log audit, complaint `SUBSTANTIATE`, sterilization filing, payment/refund, activations) were already stated in §3.

Orchestrator post-check: `diff PRD_FINALIZED.md PRD_COMPLETED.md` shows exactly 29 changed lines; all three PRD files are 448 lines; heading set is byte-identical between FINALIZED and COMPLETED (no new sections). Steps 8 and 9 touched only `workspace/PRD_*.md` — no `implementation/`, `test_suite/` or `test_helpers/` file changed after the clean Step-7 sweep, so the 8×87/87 result stands as the final state.

---

# PIPELINE COMPLETE — task_0854_body_art_tattoo_permit

All 9 steps done. Final: **87/87 tests passing across all 8 stability rounds**, 0 deletions, 1 `test_suite/` fix, 0 `test_helpers/` fixes, 1 `implementation/` fix (44 call sites). 12 entities, 58 endpoints, 64 errors.
