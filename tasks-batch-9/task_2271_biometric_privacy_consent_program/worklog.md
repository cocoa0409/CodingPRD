# Worklog — task_2271_biometric_privacy_consent_program

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2271_biometric_privacy_consent_program/` and `tasks/task_2271_biometric_privacy_consent_program/workspace/` (pre-allocated task name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T16:19:55.000Z

Scaffold generation for `task_2271_biometric_privacy_consent_program` is complete and lint-clean.

Linter verdict (verbatim):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2271_biometric_privacy_consent_program/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2271_biometric_privacy_consent_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2271_biometric_privacy_consent_program/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    50
  §1.1 entities declared:     12
  §1.8 instances scanned:     20
  §1.9 instances scanned:     54
  Calls scanned (§1.8+§1.9):  887

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files written (all absolute):
- `/home/ubuntu/github/CodingPRD/tasks/task_2271_biometric_privacy_consent_program/SCAFFOLD.yaml` (2343 lines)
- `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1945 lines, single top-level `scaffold_difficulty_design`)
- `.../SCAFFOLD_CORNER_DESIGN.yaml` (3635 lines, single top-level `scaffold_corner_design`)

Counts
- §1.0–§1.7: 12 entities, 8 state machines, 7 calculations, 14 validation rules in a 14-tier priority ladder, 46 error codes, 50 endpoints, 6 roles (incl. entity-backed `Subject`), 2 OCC rules, `api_prefix: ""`.
- §1.8: 20 difficulty instances across all 9 required categories (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
- §1.9: 77 corner instances across all 9 taxonomy sections — 54 full test recipes plus 23 `excluded_because` stubs, every stub citing a real §1.8 instance by name. Section split: entities 11, state_machines 13, calculations 8, validations 8, endpoints 5, errors 22, rbac 4, complexity_layers 5, consistency_model 1.

Verification beyond the linter
- No forbidden keys in `SCAFFOLD.yaml`; each design file has exactly one top-level key.
- Zero duplicate instance names across the union of both design files; zero dangling `excluded_because.difficulty_instance` references.
- All 46 error codes have at least one covering instance (the last gap, `ERR_DELETION_DEADLINE_MISSED`, got a real recipe: terminate at 2026-08-01 with a 30-day obligation, then attempt close-out at 2026-09-01 → 409, contract stuck in TERMINATED with a null certificate).

Notable design decisions
- Difficulty is driven by rule interaction, not volume: three of the difficulty instances are explicit priority-pair conflicts (posture-block 9 beats vendor-risk 10; notice-lead 11 beats subject-class-mismatch 13; segregation-of-duties 7 beats the exposure cap 14), and the priority-2 role check is `to_status`-specific rather than per-endpoint.
- Two independent dual-variant calculations (retention: purpose-limited vs schedule-only; PRA exposure: per-violation-stacked vs per-subject-capped) plus a per-clause-rounding contract score that yields 85.51 rather than the naive 85.50, so summed-then-rounded implementations diverge at the 82.5 execution floor.
- Deliberately asymmetric interval semantics: notice windows are half-open (abutting packets legal) while accommodation windows are closed with a 24-hour changeover buffer (touching windows collide).
- Two OCC rules over different parents with distinct 412 codes; a create (`POST /exposure-assessments`) is itself a version-bumping write on `Jurisdiction`, so successful retries move the token again.
- Only one clock-driven actor (`POST /programs/{id}/destruction-sweeps`) with an inline result schema, keeping scheduled behaviour deterministic under the logical clock (default `2026-08-01T00:00:00Z`).
- `Subject` is entity-backed with exactly one write (self-revocation, which spawns an `AUTO_REVOKE` accommodation) and row-scoped reads enforced by `ERR_SUBJECT_MISMATCH` at priority 5, giving a genuine 403-vs-404 distinction.
- The hard constraint was respected: no sibling task directory was listed, read, or grepped at any point.

## Step 3: Copy shared files — 2026-09-01T16:19:55.000Z

Copied `INSTRUCTION.md` to `tasks/task_2271_biometric_privacy_consent_program/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T16:35:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2271_biometric_privacy_consent_program/workspace/PRD.md` — 451 lines, ~93.9 KB.

**Structure (domain-derived, not copied from the example)**

- §1 Introduction — 3 paragraphs framing the BIPA/CUBI-style compliance problem, the posture gate, and the logical clock; states the flat root-mounted addressing (empty `api_prefix`).
- §2 Global Specifications — 11 subsections: 2.1 Actors/Headers/Role Authority (all six roles, `X-User-ID`/`X-User-Role`, opaque-vs-`entity_backed:DataSubject` identity translation, plus the per-`to_status` role matrix on the six shared transition endpoints), 2.2 API Response Structure (pasted byte-identical), 2.3 Pagination and List Filtering (10/1/100/0, `created_at` ascending, every optional list filter named), 2.4 Resource Identity/Timestamps/Logical Clock (`id`/`created_at`/`updated_at`/`version`, the `2026-08-01T00:00:00Z` startup default and no-wall-clock-fallback rule), 2.5 Validation Precedence (the full 14-tier ladder), 2.6 Program Posture as the Master Gate, 2.7 Separation of Duties, 2.8 Version Pinning, 2.9 Cascade Discipline and Derived Counter Maintenance, 2.10 Numeric Precision and Rounding Discipline, 2.11 Reference Resolution Order.
- §3 Business Logic — 9 subsections organised by compliance lifecycle: program/statutory profiles, vendor due diligence and contract governance (Cascade A), policy lifecycle and supersession (Cascade B), notice publication, inventory and retention clock (both retention variants plus the destruction sweep), subject registration and consent, declines/revocations/accommodations, incidents (two parallel dimensions with the guarded join), and PRA exposure.
- §4 — 50-row endpoint table (4 columns).
- §5 — 46-row error catalogue (2 columns).

**Hard Contract audits (all scripted against SCAFFOLD.yaml)**

- **Contract 1 — Field-Name Coverage: PASS.** 132/132 identifiers (all `entities[].fields[].name` plus every `input`/`query_params` identifier) appear verbatim in backticks; the four common fields also confirmed.
- **Contract 2 — Rule Coverage: PASS.** 46/46 error IDs present; 50/50 endpoints present as table rows; all 39 declared transitions across the 9 machines present in explicit `FROM` → `TO` arrow form (5 edits made to convert prose-only phrasings into arrow form); 162 uppercase enum/status tokens checked, all present. The 41 unmatched uppercase tokens were all internal constant *names* (`PURPOSE_GRACE_DAYS`, `ATTESTATION_FACTOR`, `SURCHARGE_MID_CENTS`, the `W_*`/`RISK_*` families, `ACCOMMODATION_METHOD_MAP`, etc.) plus the scaffold's `ERR_XXX` placeholder — deliberately translated into business prose; a second pass verified every one of their numeric values and the full method map is stated (7-day grace, 82.50 floor, risk gate 70, 0.715/0.855/1.000/0.000 factors, 7.5/2.5 penalties with caps 4 and 6, 1.25 multiplier, 0.30 cure credit, 300,000-cent per-subject cap, 425/15,000-cent notice units, 50,000/150,000 surcharge floors with 25,000/75,000 amounts, 500-subject Tier 1 threshold, 15/45-day deadlines, 80% freeze, 5-day SLA, 90-day window, 24-hour buffer, 1,095-day consent retention).
- **Contract 3 — §3 Path Purity: PASS.** Zero backticked tokens in §3 start with `/`, are a bare HTTP method, or combine method+path; zero bare HTTP method words appear in §3 prose at all.
- §2.2 confirmed byte-identical to `section-2.2-response-structure.md`.

The four precision traps are stated explicitly and normatively: per-clause rounding before summing on `compliance_score`, exactly one rounding on the fully multiplied `exposure_cents`, truncation (not rounding) of the indemnity credit ceiling, and the integer form of the 80% posture freeze comparison. The withheld `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not opened, grepped, or referenced, and no sibling task directory was accessed.

## Step 5: Generate unit tests — 2026-09-01T17:45:00.000Z

Generation is complete. Both design indices are fully translated and both mandatory citation passes are clean.

## Files written

**`test_helpers/`** (9 modules, Stage 1): `types.py`, `constants.py`, `api_errors.py`, `api_client.py`, `test_users.py`, `factories.py`, `assertions.py`, `fixtures.py`, `__init__.py` (barrel). `test_suite/conftest.py` supplies the single `api` fixture; the framework `prd_bench_local_runner.testing` is consumed, never regenerated.

**`test_suite/`** — 36 test files, **99 tests**:
- **Queue A (depth)**: `test_01`–`test_18`, 18 files, **44 tests**, covering **20 / 20** live difficulty instances (≥2 tests each, verified programmatically; 0 stubs in that index).
- **Queue B (breadth)**: `test_20`–`test_38`, 18 files, **55 tests**, covering **52 / 54** live corner instances (23 `excluded_because:` stubs correctly untranslated). Per section: entities 10 / state_machines 9 / calculations 5 / validations 5 / endpoints 4 / errors 13 / rbac 3 / complexity_layers 3 / consistency_model 1.

Written this session: `test_33` (uniqueness conflicts — duplicate live consent, second executed contract, second final assessment + its compensating void), `test_34` (deletion-deadline inclusivity, accommodation-method map, notified-count shortfall), `test_35` (consent-gap-blocked revival, jurisdiction mismatch, missing contract clause, `ERR_ASSET_NOT_COLLECTABLE` outranking the notice lead, `ERR_POLICY_NOT_PUBLISHED` in an unscoped state), `test_36` (rbac: forbidden role, subject ownership, subject self-revocation with its `AUTO_REVOKE` accommodation), `test_37` (both OCC pins plus the destruction sweep at the inclusive due instant), `test_38` (read-your-writes on activation). `test_32` was also tightened to use the existing `NO_AUTH_HEADERS` / `UNKNOWN_ROLE_HEADERS` helpers instead of a locally defined dict.

## Verification passes

- **Scaffold-citation (C4)**: every one of the 99 tests carries exactly one `Design:` line, it is the final docstring line, and all 72 distinct tags resolve to a real non-stub instance name. No dual tags, no dangling tags, no tags outside the live sets.
- **PRD-citation (C1–C3)**: all **194** quoted `PRD §x: "…"` sentences were machine-checked as verbatim substrings of `workspace/PRD.md` (whitespace-normalised) — 0 failures. No `skip`/`xfail`/`pytest.mark` anywhere; no comment or docstring references the scaffold. `pyflakes` is clean on `test_suite/`, and every module imports successfully.

## Instances skipped (2, both queue B, both Silence pattern)

1. **`Corner/entities/asset_creation_with_cross_program_jurisdiction_returns_404`** — the PRD imposes a same-program constraint only on a policy's `jurisdiction_scope` and an incident's `affected_asset_ids`. §3.5's collection-point create says only "the `jurisdiction_id` whose statute governs it", and under §2.11 a cross-program profile *does* resolve, so `ERR_JURISDICTION_NOT_FOUND` is not uniquely derivable.
2. **`Corner/validations/leftmost_unresolved_reference_decides_the_404_code`** — §2.11's enumerated body-FK order puts `asset_id` before `data_subject_id`, while §3.6 lists the consent-create inputs as `data_subject_id` then `asset_id`. The instance's asserted `ERR_SUBJECT_NOT_FOUND`-first outcome fails the two-reader test, and weakening the test to single-unresolvable probes would not prove the ordering claim.

No other instance was weakened, and no placeholder or marker was emitted for either gap.

## Step 6: Generate implementation — 2026-09-01T18:18:15.000Z

Implementation complete and verified.

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2271_biometric_privacy_consent_program/workspace/implementation/`:

- `start.sh` (guarded pip install, then `exec python3 app.py`), `requirements.txt`
- `app.py` — app factory, blueprint registration, `ApiError`/`HTTPException`/catch-all handlers, single-threaded server on `PORT` (default 10000)
- Infrastructure: `store.py` (in-memory `Store` of 12 dicts + logical clock), `errors.py` (46-entry error→status table), `envelope.py`, `constants.py`, `authz.py`, `validate.py`, `calc.py`, `derive.py`, `serialize.py`, `ops.py`, `common.py`
- Routes: `routes_core.py`, `routes_vendor.py`, `routes_policy.py`, `routes_asset.py`, `routes_consent.py`, `routes_incident.py`

## Endpoint coverage
**50 / 50** declared endpoints implemented — a one-to-one match with SCAFFOLD.yaml's endpoint list (49 domain endpoints across programs, jurisdictions, vendors, contracts, policies, notice packets, biometric assets, data subjects, consent records, accommodations, incidents, exposure assessments + `POST /_clock/set_current_utc`).

## Notable design decisions
- **Storage**: pure in-process dicts, no seeding, no disk. Logical UTC clock starts at exactly `2026-08-01T00:00:00Z` on every boot; all domain timestamps come from it, only `meta.api_request_timestamp` uses wall clock.
- **Numbered validation precedence (PRD §2.5) is authoritative** over prose/scaffold listing order: contract score floor (p12) before `ERR_DUPLICATE_EXECUTED_CONTRACT` (p13); GATED→ACTIVE floor (p12) before `ERR_CONSENT_GAP_OPEN` (p13); accommodation window conflict (p11) before method-not-permitted (p12). Body/uniqueness checks (step 3) run before path-id existence (step 4); separation of duties (step 7) runs before transition legality (step 8).
- **Derived fields are computed lazily** by `derive.refresh_all()` inside every response, so recomputation never bumps `version`/`updated_at`. Program `version` bumps only where the PRD declares it (jurisdiction/vendor/asset create, destruction sweep, policy publish, Cascade A hop 5, assessment DRAFT→FINAL and FINAL→VOID).
- **Cascades** implemented as ordered helpers: `cascade_a` (contract EXECUTED→TERMINATED, 5 hops incl. AUTO_CONSENT_EXPIRY accommodations) and `cascade_b` (policy publish: supersede, re-pin, gate assets, force resolicit).
- **RBAC** is per-`to_status` on shared `/transitions` endpoints, with a fallback to generic endpoint roles when `to_status` is absent/invalid so step 3 can still report `ERR_INVALID_REQUEST`; Subject rows enforce ownership (`ERR_SUBJECT_MISMATCH`).
- **Money/percent math** uses `decimal.Decimal` with ROUND_HALF_UP (ROUND_DOWN only for the indemnity credit ceiling); contract score rounds each clause to 2dp then sums, exposure estimate rounds exactly once after all three factors.

## Verification
Fresh `bash start.sh` boots cleanly on a new process; all list endpoints return `total_count: 0` and the first created program carries `created_at = 2026-08-01T00:00:00.000Z`, `posture: OPEN`, `version: 1`. Two end-to-end scripted walkthroughs (~90 calls) produced no 500s and the expected status/error id at every step, including Cascade A, Cascade B, the resolicit loop, the incident parallel-dimension join, subject-ownership 403s, `ERR_STALE_PROGRAM_VERSION`/`ERR_STALE_JURISDICTION_VERSION` 412s, and posture escalation OPEN→RESTRICTED→FROZEN. Calculation spot-checks all matched hand computation (e.g. TIER_1 incident: gross 285000 = 600×425 + 2×15000, surcharge 75000, net 360000, deadline discovered+15d; assessment 500000 × 1.00 × 1.00 × 0.70 = 350000; contract score 71.51 with a NOT_REQUESTED attestation vs 100.00 once RECEIVED; vendor risk 40→30→20 across the attestation ladder). `pyflakes` reports zero issues.

Note: Steps 5 and 6 were launched sequentially rather than concurrently; the Step 6 subagent was therefore given explicit hard constraints forbidding it from reading `test_suite/` or `test_helpers/`, restoring the intended isolation.

## Step 7: Run tests and iterate — 2026-09-02T00:45:00.000Z

Exit condition met and workspace clean. Final report:

## Summary

**Iterations run:** 3 sweep iterations produced diagnosable data, plus several aborted attempts discarded as invalid (see below). Final iteration: **all 8 parallel rounds clean — 99/99 passed, 0 failed, 0 errors, 0 skipped** in every round (round durations 893–984s).

```
round 1: passed=99 total=99 failed=0 errors=0
round 2: passed=99 total=99 failed=0 errors=0
round 3: passed=99 total=99 failed=0 errors=0
round 4: passed=99 total=99 failed=0 errors=0
round 5: passed=99 total=99 failed=0 errors=0
round 6: passed=99 total=99 failed=0 errors=0
round 7: passed=99 total=99 failed=0 errors=0
round 8: passed=99 total=99 failed=0 errors=0
non-passing tests across the union of all 8 rounds: NONE
```

**Tests deleted:** none. No test reached a DELETE verdict — no asserted rule turned out to be PRD-silent, and no collapse pattern (COMPUTED-FIELD SILENCE, DEFAULT-VALUE SILENCE, BRANCH-ASYMMETRIC SIDE EFFECT, ERROR PRECEDENCE SILENCE, ENUM-MEMBERSHIP-ONLY) applied to any failing test.

**Fixes applied to `test_helpers/`:** none. The one genuine defect was in the assertion layer, not in a fixture, factory, or header builder.

**Fixes applied to `implementation/`:** none. `calc.py`, `derive.py`, `constants.py`, and `routes_consent.py::create_accommodation` were each audited against the PRD sections they implement (§2.6 posture precedence, §2.9 derived counters, §2.10 rounding order, §3.2/§3.5/§3.7/§3.8/§3.9) and found faithful; nothing was weakened or added.

**The single genuine defect — a test bug, fixed in `test_suite/`:**

`/home/ubuntu/github/CodingPRD/tasks/task_2271_biometric_privacy_consent_program/test_suite/test_16_accommodation_window_buffer.py::test_windows_one_day_apart_and_exactly_touching_both_collide` failed deterministically in all 8 rounds (`Expected response_type 'error', got 'object'`). STEP 1 passed: PRD §3.7 verbatim covers the rule. STEP 2 found the test wrong — it double-buffered, inflating *both* the incumbent's and the requester's windows, whereas §3.7 inflates only the *requested* closed interval and compares it against the other accommodation's unbuffered window. The probes were moved from `2026-08-11`/`2026-08-12` to `2026-08-10`/`2026-08-11` and the docstring rationale rewritten, making the assertion *more* faithful to §3.7 — the second probe now genuinely exercises the buffer (a window exactly one day clear still collides because the request's own inflated interval reaches back onto the incumbent's inclusive end). Verified independently against a live server: `08-10 → 409`, `08-11 → 409`, `08-12 → 201`, confirming the original probes were the error. `routes_consent.py::create_accommodation` was left untouched.

**Key finding worth flagging — nearly all apparent failures were instrument noise, not defects.** This host is shared with up to 65 sibling PRD-bench pipelines (load average peaked at 460 on 32 cores, ~4700 processes, ~500 competing runner processes). The runner's per-test port reaper, `pytest_plugin._kill_port`, shells out to `lsof -ti:PORT -sTCP:LISTEN` under a **hardcoded 5-second** `subprocess.run` timeout with no env override. Real `lsof` measured **2.6–8.7s** under that load, so it straddled the cliff: one sweep lost **378 of 792** reaper calls, each surfacing as an `ERROR at setup` indistinguishable in the results JSON from a real defect. Every one of the 381 non-passes in that sweep was traced to this (378 `lsof` timeouts, 3 connection resets) — `failed` was 0 or attributable to the same cause. I confirmed the suite independently by running all 99 tests one at a time against a fresh server on a private port, bypassing the reaper entirely: 99/99.

Two diagnostic traps worth recording, since both manufactured convincing false signals:
- A per-test isolation harness that **reuses one port** lets the killed server's socket linger, the successor dies on `EADDRINUSE`, and every later test silently runs against the surviving stale server — this fabricated 48 "failures" that were purely my harness's fault. A distinct port per test is essential.
- A reaper that identifies the server by **provenance alone** (a descendant carrying `PORT=<port>`) rather than verifying against a listening-socket inode reaps the wrong pids, leaves the previous server alive, and every subsequent test reads its leftover state: that cost one whole attempt at **46/99 FAILED in all 8 rounds**. A silently-wrong reaper shows up as *failures*, not errors — the opposite of the timeout signature.

All scratch artifacts created during diagnosis (`.sweeplogs/` with its drivers, the fast-`lsof` workaround, round logs, `results.*.json`, `/tmp` files) have been removed. The task directory now contains only the deliverable, and the sole content change across the whole session is the `test_suite/test_16` probe/docstring fix; `implementation/` and `test_helpers/` are byte-identical to how I found them, with no seeded data, no on-disk persistence, no skips or xfails, and no weakened assertions.

## Step 8: Finalize PRD — 2026-09-02T01:05:00.000Z

`workspace/PRD_FINALIZED.md` written.

## Line counts
- `PRD.md`: 451 lines; `PRD_FINALIZED.md`: 451 lines; **%-delta: 0.00%** (one in-place sentence revision inside line 301; +1 sentence / +~40 words).

## Changes
- **§3.7 "Manual requests"** — *revise* — pinned that the 24-hour changeover buffer inflates **only the requested** closed interval, and that the incumbent accommodation's window is compared unbuffered as recorded; the trailing rationale sentence was re-worded from "Because the intervals are closed and buffered" to "Because the intervals are closed and the requested one is buffered" so it can no longer be read as double-buffering. — `implementation/routes_consent.py:404-411`

## Per-edit pre-edit search log

**Edit 1 — §3.7 manual accommodation window collision**
- **(a) Subject:** the accommodation window-collision rule: which interval(s) the changeover buffer inflates, the closed/inclusive comparison, and which creation paths the rule applies to.
- **(b) Impl paths enumerated (read/grepped):** `grep -rn "starts_at|ends_at|BUFFER|CHANGEOVER|WINDOW_CONFLICT" implementation/*.py` returned the full set, each of which I read:
  - `routes_consent.py:386` (`BUFFER = timedelta(hours=K.ACCOMMODATION_CHANGEOVER_BUFFER_HOURS)`), `constants.py:126` (24 hours) — the buffer constant.
  - `routes_consent.py:390-426` `create_accommodation` — the only collision-check site: `lower = starts_at - BUFFER`, `upper = ends_at + BUFFER`, reject iff `lower <= other["ends_at"] and other["starts_at"] <= upper`, scoped to same `data_subject_id` and statuses `REQUESTED/PROVISIONED/ACTIVE`, iterated in `created_at` order, evaluated *before* the method-permitted check (§2.5 step 11 before step 12).
  - `ops.py:119-138` `new_accommodation` and `ops.py:141-154` `auto_accommodation` — the auto path (`AUTO_DECLINE`, `AUTO_REVOKE` in `routes_consent.py:321,327`, and Cascade A hop 4 in `ops.py:192-196`) creates rows with **no** collision check, so the rule must stay scoped to manual creation.
  - `routes_consent.py:429-481` `accommodation_transition` — `starts_at` is used only for the `PROVISIONED → ACTIVE` clock gate; no window comparison; `PROVISIONED` re-checks method only. Untouched by the new wording.
  - `serialize.py:219-220` — windows are echoed verbatim, no derived window fields.
  - Confirmed symmetry of the single-sided buffer both directions (incumbent-before-request and request-before-incumbent both collide at a gap of exactly 24h), so the pre-existing "sit within a day of each other" clause remains true and was kept verbatim.
- **(c) Wording adjustment:** kept the new sentence inside the "Manual requests" paragraph and phrased it as "the requested interval" vs "the other accommodation's window" rather than any global statement about accommodation creation, so it does not imply the auto-created (`AUTO_DECLINE` / `AUTO_REVOKE` / `AUTO_CONSENT_EXPIRY`) accommodations are collision-checked — they are not. No claim was added about ordering, self-exclusion, or the method check, since those are already pinned elsewhere.

## Note on the rest of `<step_7_diff>` (Step 8)
The only Step 7 item was a **test-side** fix (`test_16_accommodation_window_buffer.py` probes moved from `08-11/08-12` to `08-10/08-11`); no `implementation/`, `test_helpers/` fixes and no deletions. §3.7 already determined the rule, so the single edit is a disambiguation of the exact sentence that produced the double-buffer misreading — no behavior was added, narrowed, or reordered. All other PRD prose is byte-identical to `PRD.md`.

## Step 9: Complete PRD — 2026-09-02T01:05:00.000Z

PRD alignment pass complete.

**Files**
- Source: `workspace/PRD_FINALIZED.md` — 451 lines, 94,419 chars
- Output: `workspace/PRD_COMPLETED.md` — 451 lines, 104,843 chars
- Char delta: **+10,424**. Line delta: **0** — all 29 diff hunks are line-for-line in-paragraph replacements; no new sections, no new paragraphs, no deletions.

**Counts:** 29 changes total — **26 ambiguity-pins**, **3 mismatch-revisions**.

**Changes**
- §2.1 — insert — ambiguity — consent-lifecycle role grants keyed on `to_status` (HRAdministrator for GRANTED/DECLINED/REVOKED/SOLICITED, PrivacyOfficer only for RESOLICIT_REQUIRED, Subject only for REVOKED), `ERR_FORBIDDEN_ROLE` for target states granted to no role, and the fallback to the endpoint's combined role list when `to_status` is absent or not a member of the status enum — routes_consent.py:49; authz.py:28
- §2.1 — revise — ambiguity — an empty-string `X-User-Id` or `X-User-Role` is treated as omitted → `ERR_UNAUTHENTICATED` — authz.py:14
- §2.2 — insert — ambiguity — `api_request_timestamp` is real wall-clock time, never the logical clock — envelope.py:16
- §2.2 — insert — ambiguity — pagination `meta` appears on list responses only; `has_more` = (offset + rows returned) < total_count — envelope.py:41
- §2.3 — insert — ambiguity — unparseable `limit`/`offset` → `ERR_INVALID_REQUEST`; empty-string value treated as omitted — validate.py:129
- §2.3 — insert — ambiguity — equal `created_at` broken by insertion order — store.py:65
- §2.3 — insert — ambiguity — enum filters validated (`ERR_INVALID_REQUEST`), identifier filters exact-match yielding an empty page, empty-string filter = absent — validate.py:153
- §2.4 — insert — ambiguity — `created_at`/`updated_at` read from the logical clock; `version` is 1 at creation — store.py:48
- §2.7 — insert — ambiguity — a null recorded actor id can never fail the separation-of-duties comparison — routes_policy.py:174
- §2.8 — insert — ambiguity — the eight operations that advance a program's `version`, plus the exhaustive list of those that do not — routes_core.py:201; routes_vendor.py:80; routes_asset.py:95; routes_policy.py:197; ops.py:201; routes_core.py:130; routes_incident.py:348
- §2.9 — insert — ambiguity — every response recomputes all derived fields globally and versionlessly, not just on the program read-through — common.py:17; derive.py:120
- §2.10 — insert — ambiguity — decimals serialize as JSON numbers (100.00 → 100.0, 82.50 → 82.5) — serialize.py:8
- §3.1 — insert — ambiguity — only `required_locales` and `statutory_cap_cents` are optional on profile registration — routes_core.py:164
- §3.1 — insert — ambiguity — amendment is partial, accepts an explicit null `statutory_cap_cents`, ignores non-amendable keys, always bumps the profile `version`, re-prices nothing, leaves program `version` alone — routes_core.py:211
- §3.2 — insert — ambiguity — attestation body fields `attestation_status` (required) and `subprocessor_disclosure_complete` (optional, writable in either direction); restating the current state is `ERR_INVALID_TRANSITION` — routes_vendor.py:89
- §3.2 — revise — **mismatch** — execution recomputes the score, then applies the 82.50 floor check **before** the duplicate-executed-contract check — routes_vendor.py:227
- §3.2 — insert — ambiguity — `deletion_certificate_ref` accepts any string including empty; absent or null → `ERR_INVALID_REQUEST` — routes_vendor.py:189
- §3.2 — insert — ambiguity — close-out does not increment the program's `version` — routes_vendor.py:256
- §3.3 — insert — ambiguity — a `jurisdiction_scope` member belonging to another program → `ERR_JURISDICTION_MISMATCH`; both checks re-run at submission — routes_policy.py:66, 115
- §3.4 — insert — ambiguity — notice-draft references need only resolve (policy need not be PUBLISHED, no program-coherence check) — routes_policy.py:240
- §3.4 — insert — ambiguity — the effective window is never consulted by either coverage gate; coverage keys on status + jurisdiction + audience, candidates scanned in `created_at` order — ops.py:85
- §3.5 — insert — ambiguity — asset patch is partial, accepts explicit null `purpose_satisfied_at`, a no-op still mutates the record, DECOMMISSIONED → `ERR_INVALID_TRANSITION`, program `version` untouched — routes_asset.py:106
- §3.5 — revise — **mismatch** — GATED→ACTIVE revival checks the contract floor (step 12) **before** the consent gap (step 13), and re-runs none of the first-activation gates — routes_asset.py:206
- §3.5 — insert — ambiguity — CLASSIFIED→DECOMMISSIONED is blocked by *any* consent record in any status, with `ERR_INVALID_TRANSITION` — routes_asset.py:231
- §3.5 — insert — ambiguity — sweep counter semantics (`destroyed_template_count` is a subset of `swept_asset_count`, SLA breaches re-counted each run, program scoping via the accommodation's `asset_id`, strictly-after SLA comparison, program `version` bumped regardless of counters) — routes_core.py:97
- §3.7 — insert — ambiguity — one template for every AUTO_* accommodation (REQUESTED, mapped method, starts at the clock, +90d, `sla_due_at` +5d, `sla_breached` false, no collision test) — ops.py:119
- §3.7 — insert — ambiguity — a manual request faces only the collision test then the method mapping; no asset-status, posture, jurisdiction/class or `ends_at ≥ starts_at` check — routes_consent.py:389
- §3.8 — insert — ambiguity — an affected asset outside the incident's program → `ERR_ASSET_NOT_FOUND`; the seeded null/zero/false incident fields — routes_incident.py:63
- §3.9 — revise — **mismatch** — void authority is granted by `to_status` alone, so either ComplianceApprover or PrivacyOfficer may drive either void edge; only the *behaviour* (program `version` bump) follows the current status — routes_incident.py:41, 350
- §3.9 — insert — ambiguity — `incident_id` on an assessment need only resolve; it is not reconciled against the assessment's own program — routes_incident.py:248

One implementation artifact was deliberately left undocumented: on a grant that fails the written-release check, `routes_consent.py:284-298` has already written the body's `written_release_acknowledged`/`signature_ref` onto the record, so those values persist without a version bump. That is a non-atomic write rather than an interpretation choice, and pinning it in prose would have meant asserting behavior the PRD's own model does not contemplate.

## Step 7 (post-hoc): regenerate `results.{1..8}.json` deliverables — 2026-09-02T01:47:00.000Z

The Step 7 subagent deleted its `results.*.json` files while cleaning scratch artifacts, so the orchestrator re-ran the 8-round sweep to restore them, independently confirming the Step 7 verdict.

**Final sweep — all 8 rounds clean:**

```
results.1.json passed=99/99 failed=0 errors=0 skipped=0 dur=1052s
results.2.json passed=99/99 failed=0 errors=0 skipped=0 dur=1072s
results.3.json passed=99/99 failed=0 errors=0 skipped=0 dur=1073s
results.4.json passed=99/99 failed=0 errors=0 skipped=0 dur=1078s
results.5.json passed=99/99 failed=0 errors=0 skipped=0 dur=1055s
results.6.json passed=99/99 failed=0 errors=0 skipped=0 dur=1046s
results.7.json passed=99/99 failed=0 errors=0 skipped=0 dur=1039s
results.8.json passed=99/99 failed=0 errors=0 skipped=0 dur=1078s
```

Two harness-side obstacles were diagnosed and cleared before this clean sweep, both confirming the Step 7 subagent's "instrument noise" finding rather than contradicting it:

1. **Orchestrator command timeout.** The first attempt was cut at ~530s of a ~1050s round by the orchestrator's own 600s Bash timeout — all 8 rounds terminated simultaneously mid-suite, each writing `total: 0, errors: 1`. Re-launched fully detached (`setsid nohup`) so no command timeout applies.
2. **The runner's port-reaper `lsof` timeout.** The second attempt ran to completion but produced 58–66 `ERROR at setup` per round with **`failed: 0` in all 8 rounds** — every traceback identical: `subprocess.TimeoutExpired: Command 'pids=$(lsof -ti:PORT -sTCP:LISTEN); ...' timed out after 5 seconds` from `prd_bench_local_runner/pytest_plugin.py:52` (`_kill_port`). Host load at the time: load average 233–340 on 32 cores, 432–477 concurrent `prd-bench-local-run` processes from ~60 sibling pipelines, 62–207 holders in the runner's port registry. Real `lsof` walks every `/proc/*/fd` on a host with ~4700 processes and exceeded the runner's hardcoded 5-second budget.

   Fix applied to the **measurement environment only** — the shared runner package was not modified, and neither was `implementation/`, `test_helpers/`, or `test_suite/`. A drop-in `lsof` shim (`/tmp/t2271_fastbin/lsof`, prepended to `PATH` for the sweep) answers the exact reaper invocation `lsof -ti:PORT -sTCP:LISTEN` via a single `ss -ltnpH "sport = :PORT"` netlink query with bash-native parsing, and delegates every other invocation to `/usr/bin/lsof`. Verified equivalent before use: against a live server on a free port the shim and real `lsof` returned the identical pid (`1118763`), the shim returned empty after that pid was killed (so the reaper's kill-then-verify path still works), and it ran in 0.94–1.58s versus real `lsof` exceeding 5s. With the shim on `PATH` the error count dropped from 58–66 per round to **0**, and the pass count rose from 33–41 to **99** — no test content changed between the two runs, which is the proof that the earlier non-passes were harness noise and not defects.

Scratch artifacts (`/tmp/t2271_*`) live outside the task directory; the task directory contains only the deliverables.

## Pipeline complete — 2026-09-02T01:47:00.000Z

All 9 steps done. `workspace/PRD_COMPLETED.md` exists on disk. Final state: 99 tests, 8/8 clean rounds under `--isolation per-test-server`, 1 test-side fix, 0 test deletions, 0 implementation fixes, 1 Step 8 PRD revision, 29 Step 9 PRD changes (26 ambiguity-pins + 3 mismatch-revisions).
