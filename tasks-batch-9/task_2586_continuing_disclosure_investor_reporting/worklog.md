# Worklog — task_2586_continuing_disclosure_investor_reporting

## Step 1: Create task directory — 2026-09-03T15:11:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2586_continuing_disclosure_investor_reporting` and its `workspace/` subdirectory. Index 2586 was pre-assigned by the invoking command; no scan of ./tasks/ was performed and no other task directory was created.

## Step 2: Generate Scaffold — 2026-09-03T17:06:00.000Z

All three scaffold artifacts are complete and lint-clean.

## Files written
`/home/ubuntu/github/CodingPRD/tasks/task_2586_continuing_disclosure_investor_reporting/`

| File | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` (§1.0–§1.7) | 4046 | 197 KB |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8) | 2357 | 159 KB |
| `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9) | 5503 | 354 KB |

## SCAFFOLD.yaml contents
- 11 entities (flat topology), 11 state machines (cyclic), 3 §1.2.1 concurrency rules, 14 calculations, 40 ordered validations, 54 endpoints, 52 error codes, 4 roles (`segregation_of_duties` role model, `immediate` consistency, `beyond_expert`).
- Domain: SEC Rule 15c2-12 continuing disclosure — undertaking inventory + weighted content requirements, annual report cycles with 210-day+business-day-roll due dates, ten-business-day material-event window over a 14-date market-holiday calendar, EMMA-style submit/reject/resubmit/confirm with supersede corrections, failure-to-file events with five-year official-statement lookback (dual variant), direct placements with materiality-ratio classification, defeasance/rating actions, dissemination-agent engagement with tiered invoicing and calendar monitoring, and a dated `calendar-sweeps` batch.
- Structural constraints honored: `SCAFFOLD.yaml` contains neither design key; each design file has exactly one top-level key.

## Design index instance counts
- **§1.8 difficulty design: 18 instances** (9 rule blocks × 2 instances).
- **§1.9 corner design: 73 instances** across 8 sections — entities 13, state_machines 19, calculations 12, validations 9, endpoints 6, rbac 6, cross_cutting_complexity_layers 6, consistency_model 2. 60 carry full `test_recipe`s; 13 are `excluded_because` stubs, every one citing a difficulty instance that exists by name. No `errors` section was emitted (Table 6 declares no claim-type rows); instead all 52 error codes are verified triggerable somewhere in the two design files.

## Verification performed
- `scaffold_lint.py` → `VERDICT: clean lint` over 54 endpoints, 11 entities, 18 §1.8 + 60 §1.9 instances, **1111 calls**.
- `yaml.safe_load` after every chunk append; all instance names unique across the union of both design files; no stub carries a `test_recipe`; all 52 §1.6 codes present in the design text.
- Every date/numeric literal recomputed in Python (e.g. due dates 2025-01-27 / 2026-01-26 / 2027-01-26, deadlines 2026-07-27 / 2026-08-11 / 2026-08-13, sweep risk score 74.00 → TIER_2, invoice floor 300000, completeness 30.00 and 100.00).

Two scaffold defects found and fixed while writing §1.9: `ERR_NO_CONTENT_REQUIREMENTS` was unreachable behind the weight-closure check (priorities 17/18 swapped and documented as a cascading pair), and `MATERIAL_EVENT_MISSED` failures were unremediable (the remediate precondition demanded a filing of a terminally-MISSED notice; §1.2 and priority 31 now share a two-arm subject-match rule).

## Step 3: Copy Shared Files — 2026-09-03T17:06:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-03T17:23:00.000Z

`workspace/PRD.md` — **508 lines**, built incrementally (one `Write` + eight `cat >>` appends), so no truncation occurred.

Top-level sections: `## 1. Introduction` (L3), `## 2. Global Specifications & System-Wide Principles` (L11), `## 3. Business Logic & Workflows` (L197), `## 4. Endpoint Definitions` (L389), `## 5. Error Code Catalogue` (L450). §2 has 12 subsections; §3 has 11 subsections (3.1 debt inventory, 3.2 undertaking register, 3.3 cycles/due dates/content, 3.4 assembly & withdrawal, 3.5 listed events & the ten-business-day window, 3.6 direct placements, 3.7 repository submission surface, 3.8 failure-to-file/risk/posture/remediation, 3.9 official statements & the five-year lookback, 3.10 engagements/monitoring/invoicing, 3.11 the calendar sweep).

Tail confirmation (verified by orchestrator, not just the subagent): file ends with the last row of the §5 error table, `| ERR_ESCROW_INSUFFICIENT | 409 |`, a real section boundary — not mid-sentence.

Hard Contract reports: **Contract 1 Field-Name Coverage PASS** (124 unique required names, 0 missing). **Contract 2 Rule Coverage PASS** (40 validation priorities as a normative numbered list in §2.10 with error id/HTTP status/applies_to plus 4 ordering rationales; 3 OCC rules in §2.8; all 69 state-machine transitions incl. 8 compliance_posture bands, both sibling-branch forks with disjoint side-effect sets, self-loops, cascade-only edges; all 12 calculations with pinned step orders/constants/boundary directions and order-pinning worked examples; all 52 error ids; all 54 endpoints; every enum literal verbatim). **Contract 3 §3 Path Purity PASS** (272 distinct backticked tokens in §3, 0 violations).

Additional verification: §2.2 byte-identical to `section-2.2-response-structure.md`; §4 table 54 rows with per-row role sets matching `endpoints[].roles`; §5 table 52 rows, no duplicates, scaffold ordering; fuzzy-word scan 0 hits; no pseudocode.

Scaffold inconsistencies resolved (3): (1) `(issuer_program_code, series_designation)` uniqueness has no error code in the scaffold — stated as a data constraint without inventing a code; (2) defeasance escrow threshold — wrote the more specific per-type state-machine version citing `ERR_ESCROW_INSUFFICIENT` over priority 34's general form; (3) cycle withdrawal source states — followed the state machine plus error catalogue (`DRAFTING` and `READY_TO_FILE` only), not the transition precondition text that also listed `DELINQUENT`.

Neither design index was opened, grepped, or referenced, and no sibling task directory was read.

## Step 6: Generate Implementation — 2026-09-03T17:55:00.000Z

(Logged before Step 5 because Step 6 returned first; the two ran concurrently.)

The implementation is complete.

## Files written
`workspace/implementation/`

| File | Lines | Contents |
|---|---|---|
| `start.sh` | 9 (+x) | guarded `pip install`, `PORT` default 10000, `exec python3 app.py` in the foreground |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 49 | Flask app, `sort_keys=False`, 4 blueprints, `ApiError`/`HTTPException` handlers, `app.run(host="0.0.0.0", port=$PORT)`, no seeding |
| `core.py` | 628 | in-memory `Store`, logical clock (default `2026-08-01T00:00:00Z`), 52-entry error catalog, envelope+meta, auth ladder, shape validators, pagination, FK/path resolution, per-request version bookkeeping |
| `calc.py` | 187 | business-day calendar (14 holidays), due-date/deadline derivations, completeness score, materiality ratio bp, severity, marginal-tier invoice, risk score/tier/posture, monitoring lapse |
| `domain.py` | 472 | all "recompute from source" passes, termination cascade, five-year lookback, timeliness assessment, failure-event settlement, 5-step calendar sweep |
| `routes_a.py` | 263 | bond issues (incl. defease, rating-actions), undertakings, content requirements — 13 endpoints |
| `routes_b.py` | 295 | annual report cycles + cycle content items — 11 endpoints |
| `routes_c.py` | 438 | material event notices + the whole filing surface incl. the confirmation cascade and supersede — 11 endpoints |
| `routes_d.py` | 448 | failure events, direct placements, official statements, engagements, calendar sweep, `/_clock/set_current_utc` — 19 endpoints |

Total 2780 lines of Python. Storage is pure in-memory dicts; no file, sqlite, or /tmp persistence, and nothing is seeded at boot (a fresh `GET /disclosure/bond-issues` returns `total_count: 0`).

## Endpoints
**54**, exactly matching the PRD §4 table (53 under `/disclosure` + `POST /_clock/set_current_utc`); verified by enumerating Flask's url_map.

## Smoke test
Launched via `PORT=18726 bash start.sh` in the background, then killed by the PID found on that port only (no broad pkill).
- `GET /disclosure/bond-issues` → 200, empty array, correct envelope/pagination meta.
- `POST /disclosure/bond-issues` → 201 with `version: 1` and `created_at/updated_at` = `2026-08-01T00:00:00.000Z` (logical clock default honoured).
- Log confirms bind on `0.0.0.0` (both loopback and 172.31.60.172 lines); post-kill curl gets connection refused.

Three end-to-end scenarios were also driven through the Flask test client (scratch scripts in `/tmp`, since deleted, never inside the task dir) and all passed: full annual-report happy path with reject/resubmit/confirm and late timeliness; supersede/correction path (target → `SUPERSEDED`, `filed_filing_id` repointed, `billable_filing_count` unchanged, correction-reason and receipt-uniqueness gates); defeasance 4-hop cascade with post-void `DEFEASANCE` notice; delinquency sweep → 3-attempt ceiling → reassembly → `CONFIRMATION_BASIS` `FILED_LATE` → remediation; per-se determination refusal; lookback adequacy gate + SoD on posting; sweep idempotence at a fixed clock.

One bug found and fixed during this pass: rows kept a permanent `_new` marker, so a row created in an earlier request never version-bumped again (e.g. `BondIssue.version` did not advance when a filing draft was accepted). Replaced with a per-request birth token (`core.RequestCounter` / `row["_born"]`), so a row bumps exactly once per later request that mutates it, and `bump()` forces the advance where the PRD demands one without a field change (filing draft → issue, engagement → undertaking).

## Step 5: Generate Unit Tests — 2026-09-03T18:20:00.000Z

The suite is complete and both audits pass clean.

## Files written (task root, nothing inside `workspace/`)

`test_helpers/` — 2318 lines
`types.py` 468 · `api_client.py` 305 (54 methods) · `api_errors.py` 138 (52 error ids + status map) · `assertions.py` 333 · `constants.py` 131 · `factories.py` 134 · `fixtures.py` 761 · `test_users.py` 56 · `__init__.py` 42

`test_suite/` — 9583 lines, **227 tests collected**

| file | lines | collected |
|---|---|---|
| conftest.py | 50 | — |
| test_01_entity_contracts.py | 755 | 25 |
| test_02_state_machine_transitions.py | 1956 | 33 |
| test_03_derived_calculations.py | 756 | 21 |
| test_04_validation_gates.py | 1009 | 23 |
| test_05_endpoint_surface_and_rbac.py | 1095 | 34 |
| test_06_concurrency_and_consistency.py | 652 | 14 |
| test_07_variant_calculations_depth.py | 761 | 15 |
| test_08_nonlinear_paths_and_cascades.py | 786 | 19 |
| test_09_precedence_and_boundaries.py | 699 | 16 |
| test_10_cross_entity_and_invariants.py | 1014 | 27 |

**Tests per queue:** queue A (Difficulty, test_07–test_10) 77 · queue B (Corner, test_01–test_06) 150.

## Audit results (`/tmp/audit_2586.py`, exit 0, 0 problems)
- Every test carries exactly one trailing `Design:` tag; all 190 tag-bearing test functions resolve to a real instance with matching `rule_id`/`section`; no dangling tags, no dual tags.
- Difficulty coverage: **18/18 instances**, 3–5 tests each, none below the ≥2 target, none uncovered.
- Corner coverage: **60/60 non-stub instances** covered, none uncovered. All **13** `excluded_because:` stubs left untranslated, and every stub's `difficulty_instance:` pointer was grep-verified to resolve to a real difficulty instance name.
- Every docstring citation is byte-verbatim in `workspace/PRD.md` (one bad citation found and fixed: a `§2.1` role sentence was missing the PRD's `**` emphasis markers around `` `ComplianceReviewer` `` — now exact).
- Zero `skip`/`skipif`/`xfail` markers, zero placeholder/`pass` bodies; `pytest --collect-only` clean for the whole suite.

## Instances skipped
**None.** All 18 difficulty and all 60 non-stub corner instances were translated.

## Per-assert drops (instance kept, one asserted literal dropped as not uniquely derivable, with reason)
- **Cycle version literals** (`assemble_moves_the_cycle_to_ready_to_file...` `c_ver == 2`; `engagement_returns_from_suspended_to_active...` `2/3/4`): §2.4 bumps `version` on any persisted-field change and every item write re-derives the cycle score, so intermediate writes make the literals contradictory — replaced with `+1`-from-pre-read checks.
- **`waive` missing-reason / non-waivable error ids** and **`resubmit` missing `correction_reason`**: rule 40 scopes `ERR_WAIVER_REASON_REQUIRED` to the placement `classify` endpoint and rule 33 scopes `ERR_CORRECTION_REASON_REQUIRED` to `POST /disclosure/filings`, so the action-endpoint variants have no pinned answer.
- **Cycle-withdraw-while-filing-live arm**: the design asserts `ERR_CYCLE_HAS_LIVE_FILING` and a `DELINQUENT → WITHDRAWN` transition, but §3.4 pins `ERR_INVALID_STATE_TRANSITION` from any status other than `DRAFTING`/`READY_TO_FILE`. Engagement-termination arm kept.
- **"no DELETE verb exists anywhere in §1.5"**: no such section and not a per-request rule.
- Aggregated from earlier agents: completeness `score_after == 60.00` (PRD gives 40.00); a late material-event filing minting a `FailureToFileEvent` (§3.5 says it mints none); `fte_count == 2` (§3.8 dedupes per `cycle_id`); engagement `invoice_total_cents == 0` at creation (300000 floor); rating-action notice status `MATERIAL` (§3.1/§3.5 give `DETERMINATION_PENDING`); exact `*_at` string equality (§2.4 pins three fractional digits only for `created_at`/`updated_at`, so tests compare the `[:19]` instant or cross-row identity); design `$.total_count` JSONPaths at the envelope root (§2.2/§2.3 put pagination in `meta`).

One interpretive note worth relaying: the sweep tests pin `74.00 / TIER_2` on §3.8's "The pass runs **exactly once** per trigger and is never iterated to a fixed point" — a per-row escalating pass would instead yield 92.50.

## Step 7: Run Tests and Iterate — 2026-09-03T18:40:00.000Z

Clean sweep: all 8 parallel rounds at 227/227.

## Summary

**Iterations run:** 2

**Iteration 1** — all 8 rounds identical at 224/227, with the same 3 failures in every round (no flakiness; all three were deterministic test-artifact defects, not implementation bugs).

**Tests deleted:** none. All three failures survived STEP 1 (PRD verbatim-covers the asserted rule and uniquely determines it) and were resolved at STEP 2 as test bugs.

**Fixes applied to `test_helpers/`:** none. The fixtures, factories and role-header builders all traced correctly to PRD's role-to-resource model; the defects were localized to three individual test functions.

**Fixes applied to `test_suite/`:**

1. `test_suite/test_02_state_machine_transitions.py` — `test_assemble_stamps_the_assembler_and_scores_a_waived_item_at_full_weight` passed whole response *dicts* to the framework helper `assert_version_incremented(new_version: int, old_version: int)`, raising `TypeError: unsupported operand type(s) for +: 'dict' and 'int'` before any assertion could be evaluated. Now passes `assembled["version"], before["version"]`.

2. `test_suite/test_06_concurrency_and_consistency.py` — `test_the_withdraw_response_already_reports_the_zeroed_score` asserted `withdrawn["version"] == 2`, but the fixture's own preparation and attestation each re-derive the cycle's persisted `completeness_score_pct` (0.00 → 50.00 → 100.00), and PRD §2.4/§2.11 require a version advance on every persisted-field change including cascaded ones — so the cycle legitimately stood at version 3 before the withdrawal and 4 after. The implementation was PRD-correct; the assertion hardcoded a count that ignored two intervening mutations. Now asserts the PRD rule actually stated: withdrawal advances the version by exactly 1 over its pre-call value.

3. `test_suite/test_10_cross_entity_and_invariants.py` — `test_calendar_acknowledgement_cures_the_suspension_and_the_same_submit_succeeds` asserted `submitted_at == "2026-08-20T00:00:00Z"`, demanding the server echo the raw clock-set string. PRD §2.4 fixes the timestamp format at three fractional digits, and the suite already pins that form elsewhere (`test_02` asserts `swept_at == "2026-08-16T00:00:00.000Z"`, which passes). This one test was the outlier. Corrected the expected literal to `"2026-08-20T00:00:00.000Z"`.

**Fixes applied to `implementation/`:** none. No implementation defect was found — every failure traced to the test layer, so no PRD-required check was weakened and no endpoint, field, or side effect was added.

**Final state:** 8/8 rounds, 227/227 tests, zero failures and zero errors, verified across the full parallel sweep under `setsid` (no reaping signature: no `Terminated` server logs, rounds finished at staggered times).

### Orchestrator verification (independent of the subagent's claim)
`ls` + `json.load` over `workspace/implementation/results.{1..8}.json` — all eight files present (78 KB each, written 18:34) and each reports `passed=227 total=227 failed=0 errors=0`.

### Step 8 skip decision
Step 7 exited on iteration 2, not the first sweep, with 3 `test_suite/` fixes. The Step 8 skip condition requires **all four** counters at zero (0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, 0 `implementation/` fixes); the `test_suite/` fixes alone disqualify the skip, so Step 8 runs. Two of the three fixes (version-advance counting under cascaded re-derivation; the three-fractional-digit timestamp form on `submitted_at`) are exactly the kind of PRD under-determination Step 8 exists to pin. Note for Step 8's expectations: there were **zero** `implementation/` fixes, so a near-empty diff over PRD.md is a legitimate outcome here.

## Step 8: Finalize PRD — 2026-09-03T18:48:00.000Z

`PRD_FINALIZED.md` written with exactly one edit.

## Line counts
- `PRD.md`: 508 lines → `PRD_FINALIZED.md`: 510 lines (+2, **+0.39%**)

## Changes
- **§2.5 (The Logical Clock)** — *insert* — added one paragraph pinning the serialized form of every clock-stamped `*_at` instant: same ISO 8601 UTC form as `created_at` (three fractional digits, `Z` suffix), independent of the fractional precision / UTC offset of the `current_utc` string used to set the clock; extended explicitly to `matured_at` and the sweep summary's `swept_at`; explicitly excluded date-valued fields (`occurred_at`) and the clock-setting response's verbatim echo — `implementation/core.py:155-165` (`fmt_ts` / `clock_stamp`), `routes_c.py:307` (`submitted_at`), `domain.py:470` (`swept_at`), `routes_d.py:448` (echo).

## Pre-edit search log

**Edit 1 — §2.5 timestamp serialization**
- **(a) Subject identified:** the serialized string form of every timestamp the service emits, and the boundary between server-stamped instants, date-valued fields, and echoed client input.
- **(b) Impl paths enumerated (read/grepped):**
  - `core.py:155-160` `fmt_ts` — the single formatter; always `%03d` milliseconds, `astimezone(utc)`, `Z` suffix. Sub-millisecond input truncates (`microsecond // 1000`), so I claimed only "three fractional digits" and made no rounding claim.
  - `core.py:163` `clock_stamp` → every business `*_at`; `core.py:168` `wall_stamp` → `meta.api_request_timestamp` (already pinned by §2.2, left untouched).
  - `core.py:226-239, 278-291` — `created_at` / `updated_at` via the same formatter.
  - All 12 `clock_stamp()` callsites: `routes_b.py:125` `assembled_at`, `:246` `attested_at`; `routes_c.py:97` `determined_at`, `:307` `submitted_at`, `:392` `repository_confirmed_at`; `routes_d.py:73` `remediated_at`, `:279` `reviewed_at`, `:311` `posted_at`; `domain.py:206` `defeased_at`, `:209` `matured_at`, `:470` `swept_at`.
  - `domain.py:331-346` — `filed_at` is *copied* from `submitted_at`/`repository_confirmed_at`, not freshly stamped; both are already `fmt_ts` strings, so the form claim holds without contradicting §3.8's basis-instant rule.
  - `domain.py:158-166` — `occurred_at` is a **calendar date** (`due_date` / `filing_deadline_date` `.isoformat()`), read back with `parse_date_str` at `domain.py:276`.
  - `routes_d.py:442-448` — `/_clock/set_current_utc` returns `data["current_utc"]` **raw**, not normalized.
  - `grep isoformat()` across all route/domain files — confirmed no other timestamp-shaped value bypasses `fmt_ts`.
- **(c) Wording adjustments made:** (i) scoped the sentence to "those stamped instants" rather than "every field named `*_at`", because `occurred_at` is a date and would have been mis-described; (ii) added the explicit date-field carve-out naming `occurred_at`; (iii) added the clock-echo carve-out so the normalization is not read as applying to `/_clock/set_current_utc`'s response; (iv) said "three fractional digits" rather than any rounding rule, since the impl truncates sub-millisecond input; (v) added "or UTC offset" to cover `fmt_ts`'s `astimezone(utc)` normalization without over-specifying.

## Candidate rejected — no change needed
**Version advance on cascaded re-derivation (candidate a).** `core.py:242-291` implements: at most one `version` bump per row per request, only when a persisted field actually differs from its pre-request snapshot (or when forced via `bump()`), and never for a row minted by the same request. PRD §2.4's closing sentence ("if a request changes any persisted field of a row, that row's `version` advances by one and its `updated_at` is refreshed") plus §2.11's cascade clause already determine all three properties uniquely, and the two forced bumps are stated verbatim in §3.7 (filing draft → `BondIssue`) and §3.10 (engagement → `Undertaking`). Every recompute helper (`domain.py:12-116`) guards its write with an equality check, matching the PRD's conditional exactly. Prose left verbatim.

## Step 9: Complete PRD — 2026-09-03T19:35:00.000Z

Run as **three sequential file-partitioned passes** over `workspace/PRD_COMPLETED.md` rather than one whole-implementation scan: a single agent asked to walk 2780 lines of implementation has previously produced a byte-identical no-op copy. Partition: pass 1 = `app.py` + `core.py` + `calc.py` (framework + all formulas); pass 2 = `domain.py` + `routes_a.py` + `routes_b.py`; pass 3 = `routes_c.py` + `routes_d.py`. Each pass edited the same file in place with tight `Edit` anchors, and each was handed the previous passes' relay notes (items they had spotted inside the next pass's files) plus the list of framework rules already pinned, so no pass restated another's work.

### Pass 1 — app.py + core.py + calc.py
510 lines → 510 lines; 109,662 → 115,226 chars (+5,540). **12 ambiguity-pins, 3 mismatch-revisions.**
- §2.1 — insert — ambiguity — `X-User-ID` emptiness is the literal empty string only (a blanks-only id is accepted verbatim, no trimming) and the role match is exact/case-sensitive — core.py:356
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from uppercase letters and digits — core.py:302,307
- §2.2 — revise — ambiguity — `api_request_timestamp` is wall-clock, not the logical clock — core.py:168,308
- §2.2 — insert — mismatch — requests that never reach a declared endpoint (unrouted path, bad method) get the error shape with an **empty** `meta`, `ERR_INVALID_REQUEST`, and the transport's own 404/405 — app.py:35-39
- §2.3 — insert — ambiguity — non-integer / blank `limit`/`offset` also yield `ERR_INVALID_PAGINATION`; whitespace tolerated; offset past the end is a success with empty `data`, full `total_count`, `has_more` false — core.py:494-515,528-534
- §2.3 — revise — mismatch — list ordering ties break by **creation order, never `id`** (rows share a logical-clock `created_at`) — core.py:297-298,519
- §2.4 — insert — ambiguity — `created_at`/`updated_at` come from the logical clock; a write leaving all persisted fields identical bumps nothing (except the two explicitly forced bumps); at most one bump per row per request; a row minted by the request stays at `version` 1 — core.py:226-239,278-291
- §2.5 — insert — ambiguity — `current_utc` parsing: `Z`/offset converted to UTC, offset-less string read as UTC, bare `YYYY-MM-DD` accepted as midnight UTC, unparseable refused with `ERR_INVALID_REQUEST` — core.py:184-196,462-470
- §2.7 — insert — ambiguity — 2-dp scores travel as JSON numbers, so `50.0`/`0.0` rather than `50.00` — core.py:220-222
- §2.9 — insert — ambiguity — a present body FK that is not a stored id (unknown string **or** wrong JSON type) yields the table's 404, not a 422; absent/`null` FKs fall through to the shape rule — core.py:554-567
- §2.10 rule 5 — insert — ambiguity — strict non-coercive shape reading: non-object body refused, absent/unparseable body read as `{}`, `null` == absent (default applies), no cross-type coercion, booleans are not integers, strings stored untrimmed (with the `correction_reason`/`waiver_reason` strip carve-out), dates exactly `YYYY-MM-DD` and a real day, unknown fields ignored; also `disclosed_event_ids` elements must be non-empty strings — core.py:385-484
- §2.11 — insert — ambiguity — pinned status sets: `open_obligation_count` = cycles in `DRAFTING`/`READY_TO_FILE`/`FILING_IN_PROGRESS`/`DELINQUENT` + issue notices in `DETERMINATION_PENDING`/`MATERIAL`/`FILING_IN_PROGRESS`; `open_material_event_count` = issue notices in those three — calc.py:74-75
- §2.12 — insert — ambiguity — filters match by exact case-sensitive string equality; unrecognised query params ignored — core.py:522-526
- §3.11 — revise — mismatch — sweep iterates `created_at` ascending with creation order (not `id`) as tie-break — core.py:297 via domain.py:406-460
- §4 preamble — revise+insert — mismatch+ambiguity — same ordering fix for list endpoints; paths match with or without a trailing slash; the sweep summary and clock echo still carry `response_type` `object` — core.py:334-344, app.py:20

Verified with no change needed: the 52-code error/status catalogue matches `ERROR_STATUS` exactly; the 14 market holidays match; every `calc.py` constant, multiplier table, banding threshold, marginal invoice tier, surcharge/cap/floor order, risk-score base + persisted-tier escalation, severity boundary, completeness 4dp→sum→2dp order, and `minus_five_years` Feb-29 rule already match the PRD text.

### Pass 2 — domain.py + routes_a.py + routes_b.py
510 lines → 510 lines; 115,226 → 117,774 chars (+2,548). **12 ambiguity-pins, 4 mismatch-revisions.**
- §3.1 — revise — mismatch — `series_designation` "is unique within a given `issuer_program_code`" was never enforced; now stated as descriptive with no uniqueness check — routes_a.py:28-37
- §3.1 — insert — ambiguity — added `matured_at` to the fields a fresh issue opens null — routes_a.py:52
- §3.1 — insert — ambiguity — rating action's `prior_rating`/`new_rating` are required strings of 1–32 chars — routes_a.py:101-102
- §3.1 — insert — ambiguity — the rating-change notice stamps `created_by_user_id` from the acting director and leaves `financial_obligation_ref` null — routes_a.py:113-115, domain.py:131-155
- §3.1 — revise — mismatch — hop 2's "leaving `DELINQUENT` forces a fresh derivation … and a re-run of the risk score" made the recomputation conditional; the cascade in fact always closes with a fixed sequence (issue `open_material_event_count`, counters + `content_weight_bp_total`, risk pass, `open_obligation_count`, engagement invoices) regardless of any `DELINQUENT` cycle or whether the undertaking moved, with just-terminated engagements skipped — domain.py:251-257
- §3.1 — insert — ambiguity — the defeasance-path notice mint is unguarded (no duplicate/stale/future occurrence-date checks), and the defease call answers with the updated `BondIssue` at 200, not the notice — routes_a.py:88-92, domain.py:247-249
- §3.2 — insert — ambiguity — `suspended_reason` is 1–500 chars — routes_a.py:202
- §3.2 — insert — ambiguity — reinstate never inspects the body, so any body shape is ignored — routes_a.py:211-221
- §3.2 — insert — ambiguity — no undertaking gate on `POST /content-requirements`; accepted against `SUSPENDED`/`TERMINATED` undertakings — routes_a.py:227-250
- §3.3 — insert — ambiguity — the "at least one of three" refusal sits on the shape rung, outranking the item status check and both gates — routes_b.py:200-211
- §3.3 — insert — ambiguity — `source_document_ref` is 1–200 chars — routes_b.py:202
- §3.3 — insert — ambiguity — content-waive `waiver_reason` is 1–500 chars and its absence is `ERR_INVALID_REQUEST`, never `ERR_WAIVER_REASON_REQUIRED` — routes_b.py:280
- §3.4 — insert — ambiguity — assemble never inspects the body — routes_b.py:100
- §3.4 — insert — ambiguity — the `DELINQUENT`-path assembly also re-derives every non-`TERMINATED` engagement's invoice; an assembly from `DRAFTING` does none of the three — routes_b.py:127-130
- §3.4 — insert — ambiguity — `withdrawal_reason` is 1–500 chars and withdrawal has no undertaking gate — routes_b.py:140,141-160
- §3.8 — revise — ambiguity — pre-existing events on the cycle: *every* event with that `cycle_id` keeps `kind`/`severity` and gets `days_late` refreshed, but only an `OPEN` one moves to `REMEDIATION_PENDING` — domain.py:361-382
- §3.8 — insert — ambiguity — `MATERIAL_EVENT_MISSED` takes `undertaking_id` from the notice's issue, null when that issue has no undertaking — domain.py:444-448
- §3.9 — revise — mismatch — lookback sort ties break by `created_at` then creation order (third key `_seq`) — domain.py:285
- §3.11 — revise — mismatch — step 1's "non-terminal cycles" wrongly included `FILING_IN_PROGRESS`; now the exact three statuses, with `FILING_IN_PROGRESS` left alone — domain.py:218-222
- §3.11 — revise — ambiguity — step 4 refreshes `monitoring_lapse_days` for `ACTIVE` **and** `SUSPENDED`, but only `ACTIVE` rows transition and are counted — domain.py:455-464

### Pass 3 — routes_c.py + routes_d.py
510 lines / 118,163 chars → 509 lines / 122,497 chars. **17 ambiguity-pins, 6 mismatch-revisions, plus the §5 cleanup.**
- §2.9 — revise — mismatch — added `financial_obligation_ref` to the closed list of FK-resolved fields (it 404s with `ERR_PLACEMENT_NOT_FOUND`) — routes_c.py:48
- §2.9 — revise — mismatch — carved out `disclosed_event_ids` from pass 1's universal "wrong JSON type ⇒ not-found" claim: only non-empty string elements are resolved, others fall to the shape rung — routes_d.py:203-210
- §3.5 — insert — ambiguity — `financial_obligation_ref` is otherwise unpoliced (foreign issue, any status, any `event_type`; no write-back to `linked_notice_id`) — routes_c.py:48,58
- §3.5 — insert — ambiguity — `determination_note` is 1 to 500 characters — routes_c.py:87
- §3.6 — insert — ambiguity — a negative `principal_amount_cents` fails at the shape rung while exactly 0 survives to rung 23, so capacity is reported first — routes_d.py:87,96-102
- §3.6 — insert — ambiguity — classification has no issue and no undertaking gate (a defeased/matured issue's `RECEIVED` placement is still classifiable) — routes_d.py:165-173
- §3.6 — insert/revise — ambiguity — the minted notice stamps `created_by_user_id` from the reviewer and is unguarded by §3.5's three refusals; `waiver_reason` is 1 to 500 chars and is ignored on the required branch — routes_d.py:170,182-193
- §3.7 — insert — ambiguity — a draft persists `correction_reason` as supplied (null when omitted) on ordinary and correcting drafts alike — routes_c.py:226
- §3.7 — insert — ambiguity — `correction_reason` capped at 500 characters — routes_c.py:149
- §3.7 — insert — ambiguity — submit takes no payload, body never inspected — routes_c.py:318-328
- §3.7 — insert — ambiguity — submit advances nothing for `FAILURE_TO_FILE_NOTICE` (cycle stays `DELINQUENT`) or `VOLUNTARY_FINANCIAL_OBLIGATION` (placement stays `DISCLOSURE_REQUIRED`) — routes_c.py:289-302
- §3.7 — insert — ambiguity — `rejection_reason` is 1 to 500 characters — routes_c.py:352
- §3.7 — revise — mismatch — resubmit requires `X-User-ID` to equal the filing's own `submitting_engagement_id` (PRD said "re-resolves an ACTIVE engagement for the filing's undertaking"), reason 1 to 500 chars — routes_c.py:336-340
- §3.7 — insert — ambiguity — `repository_receipt_id` is 1 to 64 characters — routes_c.py:379
- §3.7 — insert — ambiguity — a confirmed `FAILURE_TO_FILE_NOTICE` discharges nothing; its cycle stays `DELINQUENT` and the notice is remediation evidence instead — routes_c.py:410-426
- §3.7 — revise — mismatch — hop 2 also runs on a `FILED_TIMELY` cycle (advancing existing events); it only *mints* for a late cycle with no event yet — routes_c.py:413-415
- §3.7 — revise — mismatch — hop 5 keys on the program code of this filing's own undertaking and runs on every confirmation, not on "the failure event's" code — routes_c.py:434
- §3.7 — revise — mismatch — the supersede step replaces hops 1–2 and runs *before* hops 3–5 (not "finally"), and repoints `filed_filing_id` only where the subject has that field, leaving a `DirectPlacement` untouched — routes_c.py:399-409
- §3.8 — insert — ambiguity — `remediation_note` is 1 to 500 characters — routes_d.py:50
- §3.8 — insert — ambiguity — the cycle arm ignores the filing's `filing_type`; an event with a null `undertaking_id` can satisfy neither arm; the non-`CONFIRMED` refusal shares the same error id — routes_d.py:56-68
- §3.9 — insert — ambiguity — posting takes no payload, and an inadequate post persists nothing (the three computed fields stay as the last review wrote them; a successful post rewrites them before `POSTED`) — routes_d.py:291-311
- §3.10 — insert — ambiguity — the expiration/effective ordering is a shape test ahead of OCC and the undertaking gate; the initial `last_calendar_ack_date` is range-unchecked — routes_d.py:328-343,351
- §3.10 — insert — ambiguity — `ERR_ACK_DATE_OUT_OF_RANGE` is one id for both bounds and sits below the status check — routes_d.py:401-412
- §5 — the stray `52` between the header separator and the first data row is deleted (a generation artifact that broke the markdown table); no other §5 row touched.

Two items pass 3 deliberately left under-determined rather than risk a false universal: §3.7's "the undertaking of the filing's issue" on submit (impl derives it from the subject, but `create_filing` forces the two to coincide), and hop 4's "the submitting engagement's" invoice (impl re-derives every non-`TERMINATED` engagement of the undertaking, of which the active submitter is necessarily the only one).

### Totals and orchestrator verification
`PRD.md` 508 lines / 109,013 chars → `PRD_FINALIZED.md` 510 / 109,662 → `PRD_COMPLETED.md` **509 lines / 122,497 chars** (+12,835 chars over PRD_FINALIZED, +11.7%). **41 ambiguity-pins, 13 mismatch-revisions** across the three passes.

Independently verified by the orchestrator: `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (93 changed lines by `diff`), the §5 error table still holds exactly 52 unique `ERR_` rows, the §4 endpoint table still holds 54 rows, the stray `52` is gone, and the tail still ends at `| ERR_ESCROW_INSUFFICIENT | 409 |` — nothing truncated.

Pipeline complete: Step 9 has written `workspace/PRD_COMPLETED.md`.
