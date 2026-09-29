# Worklog — task_2478_occupational_licensure_portability_military_spouse_endorsement

## Step 1: Create task directory — 2026-09-02T22:53:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2478_occupational_licensure_portability_military_spouse_endorsement` and its `workspace/` subdirectory. Index 2478 was pre-assigned by the invoking pipeline; no scan/allocation of ./tasks/ was performed.

## Step 2: Generate scaffold — 2026-09-03T00:53:00.000Z

All three scaffold artifacts are complete and lint-clean.

## Files

- `/home/ubuntu/github/CodingPRD/tasks/task_2478_occupational_licensure_portability_military_spouse_endorsement/SCAFFOLD.yaml` (§1.0–§1.7; contains neither design key)
- `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `.../SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## Counts

| Section | Count |
|---|---|
| §1.1 entities | 14 (one immutable: `FeeLedgerEntry`, `common_fields: false`) |
| §1.2 state machines | 5 |
| §1.2.1 concurrency rules | 2 (OCC-only: `expected_application_version` on permit issue, `expected_evaluator_version` on review assignment) |
| §1.3 calculations | 11 (2 dual-variant) |
| §1.4 validations | 37 ordered priorities |
| §1.5 endpoints | 45 (19 GET / 26 POST) |
| §1.6 errors | 48 |
| §1.7 roles | 5 (`Applicant` and `Evaluator` entity-backed, 3 opaque) |
| §1.8 difficulty instances | 18 (9 rule_ids x 2) |
| §1.9 corner instances | 87 across all 9 sections (entities 12, state_machines 17, calculations 14, validations 18, endpoints 6, errors 6, rbac 6, cross_cutting 7, consistency 1) — 66 full recipes + 21 `excluded_because` stubs |

Domain: `licensure-portability`, prefix `/licensure`. Profile: `compliance_audit` / `workflow_orchestration`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`, topology `flat`, shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`.

Lint: `VERDICT: clean lint` — 687 calls scanned across §1.8+§1.9, all conform to §1.5, and all 14 entities' FKs have reverse-reachability. Forbidden-vocabulary sweep is clean; every `expected_*_version` payload key carries a `${var}`.

## Design adjudications

1. **Expert-plus sizing overshoot, deliberate.** 14 entities / 45 endpoints / 48 errors exceed the §0.4 Expert bands (10–15 / 20–32 / 18–30). 19 of the GETs exist solely to satisfy mandatory FK reverse-reachability, and ~12 error codes are mechanical per-entity 404s, so the "interesting" business-error count (~26) sits inside the band. Kept, per the "harder than expert" instruction.
2. **Two dual-variant calculations rather than one**, giving the `dual_variant_calc` rule two independent grounds: `substantial_equivalency_score` (STRICT_SCOPE vs UNIVERSAL_RECOGNITION — the universal pathway lifts `hours_ratio` to 1.0 and drops the critical-scope penalty) and `applicant_disciplinary_risk_index` (`reported_at` vs `action_effective_at` date anchors).
3. **Per-component waiver rounding** in `net_fee_due_cents` (round each of 5 components then sum) instead of sum-then-round — this is the falsifiable witness in `fee_waiver_per_component_rounding_beats_sum_then_round` (balance 12342, not 12344).
4. **Validation priority 6 narrowed** so the Evaluator ownership check only fires when an ASSIGNED assignment exists; priority 18 (`ERR_NO_OPEN_REVIEW_ASSIGNMENT`) owns the no-assignment case. Without this the two rules were mutually unreachable.
5. **Segregation of duties anchored on a data field**, `LicenseApplication.scope_reviewed_by_user_id`, rather than on role names — so the same human holding both the analyst and deputy roles is still blocked (priority 14 at 403).
6. **Permit expiry is a swept endpoint**, `POST /licensure/permit-expiry-runs`, not a wall-clock timer, keeping every §1.8/§1.9 recipe reproducible from an empty DB through §1.5 plus `POST /_clock/set_current_utc`.
7. **Distinct applicants used wherever a fixture needs 2+ applications** for the same profession, because priority 25 (`ERR_DUPLICATE_ACTIVE_APPLICATION`) would otherwise pre-empt the rule under test.

## Step 3: Copy shared files — 2026-09-03T00:53:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-03T01:05:00.000Z

PRD generated at `workspace/PRD.md` (433 lines, ends cleanly at a fully-written §5).

## Section list

- **§1 Introduction** — 3 paragraphs (business-context angle: portability friction, military-family relocation, ledger auditability, processing-time standards)
- **§2 Global Specifications** — 11 subsections, domain-named: 2.1 Agency Actors and RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination and List Ordering · 2.4 Resource Identity, Audit Fields and the Logical Clock · 2.5 Numeric Precision, Cents and Rounding Discipline · 2.6 Stale-View Rejection on Capacity-Bearing Writes · 2.7 Path and Foreign-Key Resolution Order · 2.8 The Order of Rejection (the full 37-step priority ladder with per-rule `applies_to` scopes) · 2.9 Cascade Discipline When an Application Leaves the Reviewable Set · 2.10 The Append-Only Fee Ledger · 2.11 Segregation of Duties
- **§3 Business Logic** — 9 subsections grouped as regulatory-frame → intake → discipline → submission → equivalency → reviewer calendar → military credit → permits → decision/mint
- **§4 Endpoint Definitions** — 45 rows, 4 columns
- **§5 Error Code Catalogue** — 48 rows, 2 columns

## Hard Contracts

```
Field coverage check:
- entities[].fields: 98 required, 98 present, 0 missing
- endpoints[].request_body: 67 required, 67 present, 0 missing
- endpoints[].query_params: 14 required, 14 present, 0 missing
- extra identifiers (id/created_at/updated_at/version, expired_count, expired_permit_ids, current_utc): all present
- state enum values: all present; enum-field values: all present; errors[].id: 48/48; roles[].name: 5/5
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 37 checked, 37 expressed in prose (single ordered ladder in §2.8), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_application_version / expected_evaluator_version + ERR_STALE_VERSION 412), 0 missing
- state_machines[].transitions: 23 checked (12 LicenseApplication, 5 CredentialEvaluation, 3 TemporaryPermit, 2 ReviewAssignment, 1 CreditAward), 23 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed with pinned evaluation order and all constants, 0 missing
- validations[] conditions: 37 checked, 37 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed, 0 missing
- entities[].fields[] structured content: 98 checked, defaults/initials/types reconstructible, 0 missing
- sibling-branch symmetry: 7 groups checked (deficiency A/B, APPROVE/DENY, EQUIVALENT/DEFICIENT_SCOPE, CLEAR/ADVERSE, permit CONVERTED/REVOKED/EXPIRED, COMPLETED/RELEASED, SUSPENDED_REVIEW→UNDER_REVIEW/→SUBMITTED), 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 683
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 diffs byte-identical against `section-2.2-response-structure.md`. Fuzzy-word scan (approximately/roughly/conservatively/about N/around N/~N) returns zero hits.

## Coverage notes worth flagging

- **One scaffold gap handled explicitly:** the `PENDING → EQUIVALENT` scope-review precondition ("`missing_scope_elements` contains no member of `critical_scope_elements`") has no `error_id` nominated anywhere in the scaffold's `validations[]` or `errors[]`. I expressed the precondition as normative and mapped its rejection to `ERR_INVALID_REQUEST` (400), evaluated after the §2.8 evaluation-write-state check, rather than leaving the implementer to guess a status code. This is the only place the PRD supplies a code the scaffold did not nominate.
- **Deliberate contrast pairs** the implementer must not conflate are stated side by side: permit windows are half-open with strict comparisons and zero buffer (touching is legal); evaluator windows are closed with an inclusive 24-hour buffer on both sides (touching and even 24-hour-separated windows collide).
- **Pinned arithmetic orders** are all called out as normative rather than incidental: waiver credit rounds per component then sums; military credit rounds per record then sums; the waiver tier keys on step-3 `gross_total_cents` (never the net); the disciplinary index clamps to 100.00 after *every* row, making it order-sensitive; the conversion credit uses the permit's pre-truncation `expires_at`.
- **Constants embedded in business context** (not tabulated): 730-day licence term rendered as "two 365-day years", 24-hour reviewer buffer, 40000-cent military full-waiver cap, 90/120/180-day pathway permit caps, 30-day grace and expedite allowances, two-cycle deficiency cap.
- `FeeLedgerEntry`'s absence of both `updated_at` and `version` is stated explicitly, as is the fact that reads of an application refresh `processing_elapsed_days` *without* bumping `version` or `updated_at`.
- Did not open `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`.

**Orchestrator truncation check (see below):** `tail` of PRD.md ends on the final `| \`ERR_PAYMENT_EXCEEDS_BALANCE\` | 422 Unprocessable Entity |` row of §5 — a real section boundary, not mid-sentence. Unique `ERR_*` tokens in PRD = 48, matching the scaffold's 48 (the scaffold's 49th, `ERR_XXX`, is the §2.2 response-format placeholder). §4 endpoint table present with all rows. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T02:35:00.000Z

Test generation is complete for `task_2478_occupational_licensure_portability_military_spouse_endorsement`.

## Files written

**Stage 1 — `test_helpers/`** (base path `/home/ubuntu/github/CodingPRD/tasks/task_2478_occupational_licensure_portability_military_spouse_endorsement/`):
`__init__.py` (barrel), `constants.py`, `types.py`, `test_users.py`, `api_errors.py` (48 `ERR_`-prefixed ids + HTTP status map), `api_client.py`, `factories.py`, `fixtures.py` (`LicensureSetup`), `assertions.py`.

**Stage 2 — `test_suite/`**: `conftest.py` plus 22 test modules.
- Queue A (difficulty index): `test_01`–`test_09` — dual-variant calcs, fee formulas, deficiency/suspension branching, transitive cascades, permit rejection precedence, threshold/interval boundaries, pathway permit eligibility, reviewer calendar buffer, compensating invariants.
- Queue B (corner index): `test_10`–`test_22` — entities, state machines, calculations, validations, endpoints, errors, RBAC/segregation, and finally `test_22_optimistic_concurrency_and_immediate_consistency.py` (OCC 412 `ERR_STALE_VERSION` on both writes, the version ladder, read-without-version-bump, submit-response immediacy).

## Counts

- **136 tests total**: Queue A **60**, Queue B **76**. Every file has >=5 tests.
- **83 distinct `Design:` tags**: 17 difficulty instances + 66 corner instances.
- Coverage against the indices, verified programmatically by walking both YAMLs: difficulty **17 of 18** non-stub instances translated; corner **66 of 66**; **zero** `excluded_because:` stubs translated (21 corner stubs correctly ignored).

## Verification run

`/tmp/verify_cites.py` (AST walk + verbatim PRD grep): `tests=136 quotes=249 distinct_tags=83 problems=0` — exactly one trailing `Design:` line per test, every docstring quote a whitespace-normalized verbatim match against `workspace/PRD.md`. A separate tag-existence check reports `bad 0` (no tag points at a missing or stub instance). pyflakes clean; all 22 modules import cleanly. No `skip`/`xfail`/`skipif` anywhere, and no reference to "scaffold" in test text.

## Instance skipped (1)

`Difficulty/cross_entity_state_dependency/discipline_finding_gated_on_assigned_review_assignment_of_calling_evaluator` — fails the unique-derivability condition. The design expects 422 `ERR_NO_OPEN_REVIEW_ASSIGNMENT` (§2.8 check 18), but check 6 (Evaluator ownership) is ordered earlier and, per §2.8, applies "only when at least one `ASSIGNED` review assignment exists for the target application". In the recipe another evaluator's `ASSIGNED` assignment does exist, so the PRD uniquely derives `ERR_OWNERSHIP_VIOLATION` 403 from the earlier check instead. Per the skip-don't-weaken rule, no test was emitted and no placeholder left behind.

## Step 6: Generate implementation — 2026-09-03T02:35:30.000Z

All remaining route modules plus `app.py` are written and the server has been smoke-tested end to end from a fresh `bash start.sh` boot.

## Files written (all under `.../task_2478_.../workspace/implementation/`)

**Launcher / deps:** `start.sh` (guarded `pip install` so per-test reboots don't re-install, then `exec python3 app.py`, `PORT` env, default 10000), `requirements.txt` (`flask>=2.0`).

**Foundation:** `app.py` (blueprint registration, `ApiError` -> envelope handler, 400/401/404/405/500 envelope handlers, `db.LOCK` acquired in `before_request` / released in `teardown_request`, `app.run(host=0.0.0.0, port=$PORT, threaded=True)`), `constants.py`, `errors.py` (48 error ids + HTTP map), `clock.py` (logical clock pinned at `2026-08-01T00:00:00Z`, never falls back to wall time), `numbers_util.py` (ROUND_HALF_UP helpers — named this way because `numbers.py` shadows a stdlib module that `decimal` imports), `db.py` (14 in-memory dicts, empty at boot, audit-triplet row factory, `_seq` tie-break), `response.py` (envelope, meta, pagination), `middleware.py`, `validators.py`, `serializers.py`.

**Services:** `services/calculations.py` (all SCAFFOLD §1.3 rules), `services/lookups.py` (existence + ownership), `services/workflow.py` (ledger append/rebalance, permit revoke/convert, assignment release/complete, reviewable-set cascade, disciplinary recompute).

**Routes (11 blueprints):** `professions.py`, `applicants.py`, `disciplinary.py`, `applications.py`, `evaluations.py`, `credit_awards.py`, `permits.py`, `evaluators.py`, `assignments.py`, `licenses.py`, `clock_control.py`.

**45 registered endpoints**, exactly matching the PRD §4 table (verified by dumping the url_map). ~2950 lines. Storage is in-memory dicts only — no SQLite, no JSON on disk, no `/tmp` cache, and nothing seeded, preloaded or hardcoded at startup.

## Smoke coverage (three scripted runs, each on a fresh boot)
Full happy path (profession -> compact -> applicant -> credential -> training record -> application -> submit -> payments -> evaluation -> evaluator -> assignment -> scope review -> discipline finding -> finalize -> credit award -> exam results -> permit -> deficiency/cure -> approve -> licence) plus: fee arithmetic (43000 gross, 10750 per-component compact waiver, 15000 exam reversal, 6000 permit fee, 4480 prorated conversion credit), `RNURSE-000001` mint, 730-day term, permit window nested cap, half-open permit collision (touching permits accepted), closed 24h-buffered reviewer calendar collision, OCC 412 on both guarded writes, capacity 409, lapsed review window 422, evaluator ownership 403 vs `ERR_NO_OPEN_REVIEW_ASSIGNMENT` 422, EQUIVALENT-with-critical-miss 400, third deficiency -> DENIED with full permit reversal + assignment release, disciplinary suspend/restore cascade (`SUSPENDED_REVIEW` -> `SUBMITTED`), expiry sweep idempotence, pagination guards, and the error envelope for unknown paths/methods/bad JSON.

## Interpretation decisions where the spec was ambiguous
1. **Timestamps:** `meta.api_request_timestamp` is real wall time; every entity timestamp comes from the logical clock.
2. **`pathway_risk_index`** is derived on read (never stored), so posting a disciplinary record bumps only the applicant's `version` plus the explicitly declared transitions.
3. **Cascade version accounting:** deny/suspend increments the application `version` once for the status transition **plus** once per revoked permit (§2.9 makes each `fee_balance_cents` recomputation a mutation); `APPROVE` increments exactly once ("once for the approval as a whole"), so `convert_permit` deliberately does not touch the application.
4. **Undocumented memos:** `PAYMENT` -> `"applicant payment"`, `PERMIT_FEE` -> `"permit fee"` (the PRD only fixes the other five).
5. **Licence mint sequence** is global (not per profession), starting `000001`; approval converts every `ACTIVE` permit in `created_at` ASC and records the first one in `converted_from_permit_id`.
6. **Scope-review / finalize parent-state gate** is mapped to check 8 (`ERR_APPLICATION_NOT_REVIEWABLE`, 409) even though §2.8's enumeration doesn't name them; the `EQUIVALENT`-with-critical-miss refusal is a 400 evaluated *after* check 10, per §3.5.
7. **Applicant-scoped lists** silently filter to the caller's own rows; single reads of another applicant's row are 403.
8. **`databases_checked`** is required but untyped (any non-null JSON accepted) and not persisted — no entity field exists for it.
9. **Evaluator `profession_code`** is accepted as a free-form non-empty string (no format constraint is declared for it, unlike `Profession.profession_code`).
10. **Body FK resolution** follows each endpoint's declared input order; invalid query enums/bools and out-of-range `limit`/`offset` are 400, never clamped.
11. **No extra gates invented:** payments have no application from-state check and disciplinary posting has no application-state check, since neither appears in check 8.
12. A permit whose nested cap lands on its own `effective_at` is issued with a zero-length window (conversion credit then computes to 0 cents), which is what the "nested cap" wording produces.

**Orchestrator note:** Steps 5 and 6 were launched as background subagents back-to-back so they ran concurrently. The impl generator was explicitly forbidden from reading `test_suite/` / `test_helpers/` / either design yaml, and its summary shows it built from INSTRUCTION.md + SCAFFOLD.yaml + PRD.md only.

## Step 7: Run tests and iterate — 2026-09-03T03:15:00.000Z

Clean 8-round parallel sweep: **136/136 passing in all 8 rounds.**

## Summary

**Iterations run:** 3 sweeps (8 parallel rounds each). Baseline was 98/136 (identical in all 8 rounds — fully deterministic, no flakiness observed at any point).

**Tests deleted:** none. Every failure traced to a test-artifact defect that could be made *more* faithful to PRD, so no test lost coverage.

**Fixes applied to `test_helpers/`:**
- `test_helpers/assertions.py` — added `normalize_instant` / `instants_equal` / `assert_instant_equals`, and routed all seven exact-field comparators (`assert_application_fields`, `assert_permit_fields`, `assert_evaluation_fields`, `assert_evaluator_fields`, `assert_assignment_fields`, `assert_applicant_fields`, `assert_fields`) through instant-aware equality. PRD §2.4 pins a three-fractional-digit rendering only for `created_at`/`updated_at`; for domain timestamps (`submitted_at`, `review_deadline_at`, `decided_at`, `closed_at`, `expires_at`, `effective_at`, `revoked_at`, `finalized_at`, ...) it pins the *instant*, not the rendering. The helpers were doing raw string equality against fraction-less literals, so `...T00:00:00.000Z` failed against `...T00:00:00Z`. This was the single root cause of 32 of the 38 failures.
- `test_helpers/__init__.py` — re-export the three new helpers.

**Fixes applied to `test_suite/`:**
- `test_04`, `test_06`, `test_09`, `test_18`, `test_19`, `test_20` — replaced 8 inline `assert x["ts"] == "...Z"` string comparisons with `assert_instant_equals` (same root cause as above).
- `test_21` (fixtures `file_whose_scope_review_the_analyst_signed`, `evaluation_resolved_on_both_dimensions`, `file_scope_reviewed_by_a_dual_role_officer`) and `test_18` (`half_reviewed_nursing_file`) — these fixtures granted the credential `["ASSESS","TREAT","SUPERVISE"]` while the profession nominates `PRESCRIBE` as critical, then recorded `EQUIVALENT`. PRD §3.5 requires that to be refused with `ERR_INVALID_REQUEST`, so the PRD-faithful implementation correctly rejected the setup ("Setup step failed", 5 tests). Fixed the fixtures to grant the full required scope; none of the five tests assert anything about scope.
- `test_20::test_an_application_carries_at_most_one_credential_evaluation` — relaxed to `validate_error_is_one_of([ERR_EVALUATION_ALREADY_EXISTS, ERR_APPLICATION_NOT_REVIEWABLE])` (status 409 still asserted exactly). Error-precedence silence: opening the first evaluation drives `SUBMITTED -> UNDER_REVIEW`, so a second attempt violates §2.8 check 8 (from-state) *before* check 11 (uniqueness), and §2.8 declares the first violated check decides — while §3.5 names the uniqueness code for "a second attempt". Both readings are PRD-faithful.
- `test_07::test_identical_windows_coexist_when_the_professions_differ` — asserted `permit["profession_id"]`, a field PRD never declares on `TemporaryPermit` (§3.8 lists no such attribute; PRD puts `profession_id` on `LicenseApplication` and on `License`, and scopes the collision test to "whose own **application** shares ... the same profession"). Rewrote the assertion to read the professions off the two applications, plus link each permit to its application — same rule, expressed where PRD puts the data.

**Fixes applied to `implementation/`:** none. No implementation defect was found; every failure was a test-artifact defect. No PRD-required check was removed or weakened.

One process note worth flagging: the first sweep attempt was reaped (all 8 rounds `Killed` at the same instant with 108 GB RAM free), because `setsid nohup ... & wait` under the background-Bash wrapper still shared a killable process group. Relaunching as a detached script (`setsid nohup bash sweep.sh ... < /dev/null & disown`) and polling for the 8 results files ran reliably for all three sweeps.

**Orchestrator independent verification:** re-read all 8 `workspace/implementation/results.{1..8}.json` directly. Every file reports `passed=136 total=136 failed=0`. The clean sweep is confirmed, not merely claimed.

**Step 8 gating decision:** Step 7 applied 0 `implementation/` fixes and 0 deletions, but it did apply `test_helpers/` and `test_suite/` fixes, so the skill's skip condition (which requires all four counts to be zero) is NOT met. Step 8 runs, with the diff above as its focus list. Notably the `test_07` fix reveals a genuine PRD/impl question (whether `TemporaryPermit` exposes `profession_id`) and the `test_20` relaxation reveals a real precedence silence — both are legitimate Step 8 targets.

## Step 8: Finalize PRD — 2026-09-03T03:22:00.000Z

`PRD_FINALIZED.md` written. Note: `test_suite/` and `test_helpers/` are not present in this workspace (only `PRD.md`, `INSTRUCTION.md`, `implementation/`, `sweep.log`), so every `<step_7_diff>` item was traced directly into `implementation/`.

## Line counts
- `PRD.md`: 433 lines -> `PRD_FINALIZED.md`: 435 lines (+2 lines, +0.46%)

## Changes (2)
- **§2.4** — insert — pins that *every* instant the API emits (audit fields, `api_request_timestamp`, `current_utc`, and all domain instants) is rendered ISO 8601 UTC with exactly three fractional digits and trailing `Z`, that whole seconds therefore render `...T00:00:00.000Z` (not `...T00:00:00Z`), that client-supplied instants are normalised to UTC rather than echoed, and that a null instant is JSON `null` — `implementation/clock.py:23-31`, used at `implementation/serializers.py:8-9,45,75,97-100,115-117,148,160,168-174,187-188,200,220-223`, `implementation/response.py:21`, `implementation/routes/clock_control.py:19`.
- **§3.5** — revise — pins the rejection precedence on opening a credential evaluation: from-state (§2.8 check 8) -> uniqueness (check 11) -> credential ownership (check 15), first violated check decides, so a second opening attempt on an application that has already moved to `UNDER_REVIEW` yields `ERR_APPLICATION_NOT_REVIEWABLE` (409), with `ERR_EVALUATION_ALREADY_EXISTS` reserved for an attempt reaching check 11 with the application still `SUBMITTED` — `implementation/routes/evaluations.py:46-58`.

## Items deliberately left unpatched
- **test_21/test_18 scope fixtures** (granted scope missing a critical element, then recorded `EQUIVALENT`): PRD §3.5 already pins the refusal as `ERR_INVALID_REQUEST` (400) evaluated after the write-state check, exactly as `implementation/routes/evaluations.py:139-146` does. Pure fixture bug; verbatim prose kept.
- **test_07 `permit["profession_id"]`**: `serializers.temporary_permit` (`implementation/serializers.py:164-176`) emits no `profession_id`, and the collision test reads applicant/profession off the two *applications* (`implementation/routes/permits.py:77-82`) exactly as PRD §3.8 words it. PRD and impl already agree; no edit could add information without inventing a field.

## Per-edit pre-edit search log

**Edit 1 — §2.4 timestamp rendering**
- (a) Subject: the wire rendering of every ISO 8601 instant the system emits, and null handling.
- (b) Enumerated/read: `clock.py` (`fmt` is the single formatter — 3 fractional digits, `Z`, `None`->`None`; `wall_now_iso`; `parse_iso8601` normalises `Z`/offset/naive input to UTC; no other formatter exists); `serializers.py` in full — `_audit` plus all 20 domain-instant fields across profession, reciprocal agreement, applicant, credential, training record, disciplinary record, application, evaluation, credit award, permit, license, ledger entry, evaluator, review assignment; `response.py:18-46` (envelope meta on success, array and error responses); `routes/clock_control.py:19` (`current_utc`); `routes/permits.py:140-153` (expiry-run payload — confirmed it returns only `expired_count`/`expired_permit_ids`, no instants); `grep -rn "isoformat|strftime|clock.fmt|wall_now_iso"` across all `*.py` to confirm no bypass path.
- (c) Adjustment: wrote the domain-instant list as "for example" rather than an exhaustive enumeration, so the rule still covers any instant field the enumeration might have omitted; added the explicit "normalised to UTC, not echoed" clause because `parse_iso8601` accepts offsets/naive input; added the null clause because `fmt(None)` returns `None` everywhere (`resolved_at`, `converted_at`, `revoked_at`, `closed_at`, `finalized_at`, `submitted_at`, `review_deadline_at`, `decided_at` are all nullable).

**Edit 2 — §3.5 evaluation-open precedence**
- (a) Subject: rejection precedence on `POST /licensure/credential-evaluations`, plus the reachability of `ERR_EVALUATION_ALREADY_EXISTS`.
- (b) Enumerated/read: `routes/evaluations.py:39-81` (lookups -> `_require_parent_reviewable(("SUBMITTED",))` -> uniqueness scan -> credential-applicant mismatch, in that literal order); `grep -rn "EVALUATION_ALREADY_EXISTS"` — exactly one raise site (`routes/evaluations.py:53`); every transition *into* `SUBMITTED`, to see whether an application can be `SUBMITTED` while already carrying an evaluation: `routes/applications.py:151-202` (`DRAFT -> SUBMITTED`, and a `DRAFT` application can never own an evaluation since creation demands `SUBMITTED`) and `services/workflow.py:127-134` (`_restore_cascade` routes an application that *has* an evaluation to `UNDER_REVIEW` and only an evaluation-less one to `SUBMITTED`); also re-read §2.8 checks 8 and 11 to confirm the numbering I cite matches the impl's actual order.
- (c) Adjustment: because that survey showed the uniqueness branch is effectively unreachable in the current impl, I phrased it as "reserved for an attempt that reaches the uniqueness check with the application still in `SUBMITTED`" — keeping the check and its code in the spec without asserting either reachability or unreachability, and without deleting a rule Step 9 might need. Also scoped the `ERR_APPLICATION_NOT_REVIEWABLE` claim with "whenever the application has left `SUBMITTED` in the meantime" rather than a blanket "a second attempt always yields 409", so the sentence stays true for every from-state (`DEFICIENT`, `SUSPENDED_REVIEW`, `DENIED`, `APPROVED`, `DRAFT`) reachable at that callsite.

**Orchestrator note on the subagent's opening caveat:** `test_suite/` and `test_helpers/` do live in the task, but at the task-directory root rather than under `workspace/`, which is why the subagent did not find them where it looked. No impact — the Step 7 diff was inlined into its prompt as the skill specifies, and it traced every item into `implementation/`, which is the alignment target. Verified `PRD_FINALIZED.md` exists at 435 lines and ends at the final §5 catalogue row.

## Step 9: Complete PRD — 2026-09-03T03:42:00.000Z

PRD_COMPLETED.md is complete and verified — it ends at the real §5 boundary (`ERR_PAYMENT_EXCEEDS_BALANCE | 422`), all 5 top-level sections and all 21 subsections intact.

## Counts

- **Source** `workspace/PRD_FINALIZED.md`: 435 lines / 88,414 bytes
- **Output** `workspace/PRD_COMPLETED.md`: 436 lines / 94,701 bytes (**+1 line, +6,287 bytes**)
- **31 changes** across 28 lines: **26 ambiguity-pins**, **5 mismatch-revisions**. No new sections; one new bullet in §2.2, everything else in-paragraph.

## Changes

- §2.1 — insert — ambiguity — a header present but empty counts as absent (401) — `middleware.py:12`
- §2.1 — insert — ambiguity — pins the exact set of applicant-scoped reads; the three unscoped collection reads (`/applications`, `/credential-evaluations`, `/credit-awards`) silently drop foreign rows from window and `total_count`, while applicant sub-collection reads refuse; professions, compacts, evaluators, review assignments and licences carry no scoping at all — `lookups.py:70`, `applications.py:141`, `assignments.py:93`, `licenses.py:16`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric chars — `response.py:15`
- §2.2 — insert — ambiguity — transport errors outside §5: `ERR_NOT_FOUND`/404, `ERR_METHOD_NOT_ALLOWED`/405, `ERR_INTERNAL`/500 — `app.py:61-90`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` -> 400; empty-string params count as absent; undeclared enum filter -> 400; boolean filters accept only `true/false/1/0`; unmatched id filter yields empty window — `response.py:49-95`
- §2.3 — insert — ambiguity — `created_at` ties (stationary logical clock) broken by persistence order — `db.py:61`
- §2.4 — insert — ambiguity — `id` is a random v4 UUID, canonical hyphenated form — `db.py:38`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` are read from the logical clock — `db.py:43-57`
- §2.4 — insert — ambiguity — `api_request_timestamp` is the one instant taken from real wall time — `clock.py:34`
- §2.4 — insert — ambiguity — inbound instants accept `Z`, numeric offset, no zone, or a bare date (-> midnight UTC) — `clock.py:39`
- §2.5 — insert — ambiguity — inbound decimals quantised half up to declared precision; decimals emitted as JSON numbers — `validators.py:88`, `numbers_util.py:36`
- §2.5 — **revise** — **mismatch** — day/year counts are the mathematical **floor**, not truncation toward zero, so a reversed reference instant yields a negative count — `clock.py:57,66`
- §2.7 — insert — ambiguity — per-endpoint body-FK resolution order (applicant->profession->credential; application->credential; application->training record; evaluator->application) — `applications.py:68`, `evaluations.py:46`, `credit_awards.py:38`, `assignments.py:39`
- §2.8 check 8 — **revise** — **mismatch** — scope review and finalisation require the parent in `UNDER_REVIEW`/`DEFICIENT`; discipline-finding, payments and opening an application impose no from-state at all — `evaluations.py:131,208`, `applications.py:214`
- §2.9 — insert — ambiguity — cascade runs permits first then assignments, each in `created_at` order — `workflow.py:105`
- §2.9 — **revise** — **mismatch** — `pathway_risk_index` removed from the stored-derived-field list; it is read-derived and never bumps `version`/`updated_at` — `serializers.py:129`
- §2.10 — insert — ambiguity — memo list made exhaustive: `applicant payment` for `PAYMENT`, `permit fee` for `PERMIT_FEE` — `constants.py:47`
- §3.1 — revise — ambiguity — `profession_code` is 2–8 uppercase **letters** only; scope element codes are `[A-Z0-9_]` — `validators.py:10,12`
- §3.1 — insert — ambiguity — every registration value mandatory except `critical_scope_elements` and `jurisprudence_exam_required` — `professions.py:22-46`
- §3.1 — insert — ambiguity — compact `expires_on` mandatory — `professions.py:97`
- §3.1 — insert — ambiguity — evaluator `profession_code` is free-form, unvalidated, need not name a registered profession, matched by exact equality — `evaluators.py:20`
- §3.3 — insert — ambiguity — sweep tie-break falls through to persistence order after `created_at` — `calculations.py:51`
- §3.3 — insert — ambiguity — no ceiling on the decay factor; a future variant timestamp yields a factor above 1.0 — `calculations.py:56`
- §3.4 — **revise** — **mismatch** — `pathway_risk_index` derived on every read rather than seeded/stored — `serializers.py:129`
- §3.5 — insert — ambiguity — scope-review `note` validated but not persisted — `evaluations.py:127`
- §3.5 — insert — ambiguity — `databases_checked` mandatory but any non-null JSON value, not persisted; the **earliest-created** ASSIGNED assignment supplies `window_end_at` — `evaluations.py:166,189`
- §3.5 — insert — ambiguity — exam-result `score` validated at 2dp, not persisted — `applications.py:250`
- §3.9 — insert — ambiguity — deficiency `reason_code` mandatory but not persisted — `applications.py:270`
- §3.9 — insert — ambiguity — decision `memo` validated but not persisted — `applications.py:350`
- §3.9 — insert — ambiguity — licence mint sequence is one **global** counter shared by all professions — `db.py:30`
- §3.9 — **revise** — **mismatch** — **every** ACTIVE permit converts (in `created_at` order, each with its own conversion credit); the licence records the **first** in `converted_from_permit_id` — `applications.py:339`, `workflow.py:68`

Everything else in the PRD already pinned impl behaviour uniquely — notably the full §2.8 rejection order, all six fee-assessment steps, the equivalency-score variants, both interval-collision tests, the permit window nested cap, the conversion-credit proration, and the entire §4 endpoint table and §5 catalogue (which match `errors.py` exactly).

**Orchestrator verification:** `PRD_COMPLETED.md` is 436 lines; last non-blank line is line 434, `| \`ERR_PAYMENT_EXCEEDS_BALANCE\` | 422 Unprocessable Entity |` — a real section boundary, not a mid-sentence truncation. §5 still carries all 48 catalogue rows. The only new `ERR_*` tokens versus `PRD.md` are the three transport-layer codes (`ERR_NOT_FOUND`, `ERR_METHOD_NOT_ALLOWED`, `ERR_INTERNAL`) documented by the §2.2 insert, which is consistent with the change list.

## Pipeline complete — 2026-09-03T03:43:00.000Z

All nine steps finished. Final artifact set: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `worklog.md`, `test_helpers/` (9 modules), `test_suite/` (conftest + 22 modules, 136 tests), and `workspace/` with `INSTRUCTION.md`, `PRD.md`, `PRD_FINALIZED.md`, `PRD_COMPLETED.md`, `implementation/` (45 endpoints) plus `results.{1..8}.json` from the final clean sweep (136/136 in all 8 rounds).
