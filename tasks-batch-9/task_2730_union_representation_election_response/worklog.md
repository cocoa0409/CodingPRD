# Worklog — task_2730_union_representation_election_response

## Step 1: Create task directory — 2026-09-04T12:51:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2730_union_representation_election_response` and its `workspace/` subdirectory. Index 2730 was pre-assigned by the invoking pipeline; no scan of ./tasks/ was performed and no index was auto-allocated.

## Step 2: Generate Scaffold — 2026-09-04T14:51:00.000Z

All three scaffold artifacts are complete and lint-clean.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2730_union_representation_election_response/`

| file | lines | bytes | top-level key |
|---|---|---|---|
| `SCAFFOLD.yaml` | 3445 | 180 KB | §1.0–§1.7 only (16 keys; neither design key present) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2580 | 199 KB | `scaffold_difficulty_design` (9 rule blocks, 27 instances) |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 8969 | 649 KB | `scaffold_corner_design` (9 sections, 104 instances) |

`python3 skills/prd-bench-scaffold-generator/scaffold_lint.py <task_dir>` → **VERDICT: clean lint** (66 endpoints, 12 entities, 27 §1.8 + 72 real §1.9 instances, 2453 calls checked).

## §1.9 section breakdown (real + stub)
entities 11, state_machines 18, calculations 15, validations 26, endpoints 9, errors 10, rbac 6, cross_cutting_complexity_layers 7, consistency_model 2 → **72 real + 32 stubs**.

Sections completed this session: `errors` (list/charge status ladders, incomplete scope rulings blocking a DDE, unrevised round at certify, accuracy-review freshness vs. revision limit, non-determinative objection, the structurally-shadowed `ERR_BLOCKING_CHARGE_PENDING`, and the 55-call rerun arc that is the only path to `ERR_BALLOT_VOTER_NOT_ON_ACCEPTED_LIST`), `rbac` (Board-exclusive determinations, analyst-cannot-attest, exact shared-op co-holders, segregation of duties by user id across role hats, `entity_backed` PlantSupervisor identity, 401-vs-403 header semantics), `cross_cutting_complexity_layers` (both OCC rules with priority ordering against 404/403/overlap, the selectively-narrow and only-partly-reversing posture cascade, the AS_PETITIONED↔AS_RULED denominator oscillation 34.31→38.89→34.31→58.33, the per-list resubmission ceiling with reset), and `consistency_model` (write responses carrying their own derived fields; a three-hop cascade visible through filtered collection reads in the same instant).

## Verification performed
- Every §1.9 instance name unique across §1.8 ∪ §1.9; no duplicates.
- All 32 `excluded_because.difficulty_instance` targets resolve to real §1.8 instance names (fixed two that named a non-existent rule id `conservation_invariant_across_compensation` → `compensating_invariant`).
- Stubs carry no `test_recipe`/`distinguishing_aspect`; every real instance has all four recipe keys.
- **All 76 error ids in §1.6 are now exercised** (audit reports 0 uncovered).
- Only 3 of 66 endpoints were unexercised; added reads so every declared endpoint now appears in §1.8/§1.9.
- Field-name audit: zero unknown `Entity.field` references anywhere in the corner design (caught and fixed `ULPCharge.is_blocking` → `blocking_requested`).
- Also corrected two `POST /classifications/{id}/reconsider` payloads that used `{ruling, ruling_rationale}`; the endpoint takes only `reconsideration_note?` and returns the row to PENDING — the dual-variant recipe was re-sequenced accordingly (reconsider → re-verify → rule EXCLUDED → re-verify).

No sibling task directory was read at any point; everything derives from the scenario text, `SCAFFOLD.yaml` itself, and the generator skill's spec/claim-extraction guide.

## Step 3: Copy shared files — 2026-09-04T14:52:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T15:15:00.000Z

PRD generation complete.

**Output:** `workspace/PRD.md` — **494 lines / 112629 bytes**, built with 10 chunked `cat >>` appends (no single giant Write). Last section heading is `## 5. Error Code Catalogue`; the file ends on a complete final table row (`| \`ERR_BALLOT_CONSERVATION_VIOLATION\` | 409 |`) — not mid-sentence, table, or list. No audit footer.

**Structure** (from-scratch skeleton, not copied from `example-prd.md`): §1 Introduction; §2 with 11 domain-named subsections (2.1 RBAC and the seven roles; 2.2 API Response Structure copied byte-for-byte from `skills/prd-bench-doc-generator/section-2.2-response-structure.md`, verified by diff; 2.3 Pagination; 2.4 Record properties + logical clock; 2.5 The two case dimensions; 2.6 Cascade discipline; 2.7 OCC; 2.8 Precision/rounding/conservation; 2.9 Business-day calendar; 2.10 Reference resolution; 2.11 the 27-rung rejection-priority ladder + 4 collision resolutions); §3 with 9 workflow subsections (3.1 docketing → 3.9 objections, blocking ULP charges, reruns, certification); §4 endpoint table (68 rows = header + separator + 66 endpoints, exactly 4 columns); §5 error table (78 rows = header + separator + 76 errors, exactly 2 columns).

**Hard Contract reports:**

```
Field coverage check:
- entities[].fields: 197 required, 197 present, 0 missing
- endpoints[].request_body: 124 required (19 input-only beyond entity fields), 124 present, 0 missing
- endpoints[].query_params: 0 required (scaffold declares no separate query_params/path_params keys), 0 present, 0 missing
Status: PASS
```
(216 unique names in the required set; verified twice — pass 1 by fenced-code-stripped backtick tokenisation, pass 2 by naive `` `name` `` substring search. Both returned an empty diff.)

```
Rule coverage check:
- validations[] with priority: 27 checked, 27 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_petition_version / expected_election_round_version + ERR_STALE_PETITION_VERSION / ERR_STALE_ROUND_VERSION + 412 all named), 0 missing
- state_machines[].transitions: 72 checked, 72 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed, 0 missing
- validations[] conditions: 27 checked, 27 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 42 endpoints / 88 side-effect items and 63 applies_to scope references checked, all expressed, 0 missing
- entities[].fields[] structured content: 220 field entries checked, 220 reconstructible from prose, 0 missing
- sibling-branch symmetry: 20 groups checked, 20 with equal prose density, 0 asymmetric
Status: PASS
```
Mechanical corroboration: all 76 error IDs appear in §1–§3 prose (not only in the §5 table); all 159 enum literals from `fields[].constraints` appear in prose; all 27 constants appear with their exact values (including the four `HOLIDAY_CALENDAR` dates and `CLOCK_STARTUP_DEFAULT` `2026-08-01T00:00:00Z`).

```
Path purity check (§3 only):
- backtick tokens scanned: 423 distinct
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```
§3 also contains zero plain-text `/labor-relations…` mentions; the only URL text in the document is the §1 mount note, §2.4's clock capability, and §4's table.

**Notes for the caller:**
- Scaffold inconsistency resolved by decision: `ElectionRound.majority_threshold`'s field description says "valid_votes_cast divided by 2 … strictly more than this", but the `ballots_tally` formula, its precision note, its two worked examples (81→41, 83→42) and `certification_timeline`'s `revised_votes_for >= majority_threshold` test all say halve-discard-fraction-add-one. The PRD states the halve/discard/add-one semantics and that equality is a union win.
- I did not open, grep, or reference `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`.
- I did not touch `worklog.md` or any sibling file; the only file written is `workspace/PRD.md`.

**Orchestrator truncation check:** verified independently — 494 lines, ends on the complete final row of the §5 error table, all 5 top-level sections and all 11 §2 / 9 §3 subsections present. Not truncated; no regeneration needed.

## Step 5: Generate Unit Tests — 2026-09-04T16:25:29Z

Stage 1 and Stage 2 are complete and verified on disk.

## What landed

**`test_helpers/`** (task root, 9 files, 2,638 lines) — `types.py` (role enum, ~35 status enums, TypedDicts for all 12 entities), `api_errors.py` (all 76 real error ids + HTTP status map, registered with the framework validators at import), `constants.py` (thresholds, holiday calendar, traditional weights, clock defaults), `test_users.py` (headers for all 7 roles incl. the entity-backed `make_plant_supervisor_headers`), `api_client.py` (72 methods, one per endpoint, plus raw probes), `assertions.py` (ISO-8601-canonicalising `parse_instant`/`assert_instant_equals`, `add_business_days` matching the PRD's anchor-excluded weekend/holiday calendar, per-entity asserts, conservation and envelope checks), `factories.py` (24 payload builders), `fixtures.py` (57 single-step helpers + 20 composite `setup_*` stages from empty DB to CERTIFIED / rerun / blocked / impounded), `__init__.py` barrel.

**`test_suite/`** (conftest + 12 test files, 11,547 lines) — **258 test functions, 283 collected cases**, produced by 12 partitioned translation agents each owning one file and one design-index slice.

## Coverage against the design indices

- **99/99 non-stub instances covered** — all 27 difficulty instances with ≥2 tests each (min 2, several 3–4), all 72 non-stub corner instances with ≥1 (many 3–5).
- **All 32 `excluded_because:` stubs untranslated**, as required.
- Audit script (`/tmp/2730_audit.py`) confirms: exactly one `Design:` line per test as the docstring's last line, every tag resolving to a real instance, no tag pointing at a stub, and **every PRD citation verified as a verbatim ≥8-word substring of `workspace/PRD.md`** — zero problems. No `skip`/`xfail`/placeholders anywhere; no "scaffold"/section/table references; no `§` characters.
- `pytest --collect-only` collects all 283 cases with no import or fixture errors; pyflakes reports no undefined names.

## Findings worth carrying forward

- **One defect I fixed**: `test_computed_values.py` used `add_voter_entry` without importing it; added to its import block.
- **Design-index defects the agents corrected PRD-first**: recipes use `section_code: "8(a)(1)"` (PRD enum is `8A1`/`8A3`/`8A5`/`8B1A`), `audience_scope: "DEPARTMENT"` (not a PRD value), a challenged-ballot `status` field (PRD names it `resolution`), and `majority_threshold == 41.50` where the PRD's halve-discard-add-one rule gives 42.
- **PRD silences left as gaps** rather than guessed: default values never stated (`contains_interrogation` etc., `resubmission_count` initial, birth counters), `eligible_voter_count` on an ungraded DRAFT list, `polls_opened_at` (field never declared), and the error id for replaying `open-polls`/`post-tally` (two own-state codes, neither uniquely assigned) — those two use `validate_error_is_one_of` plus the PRD-stated 409.
- **Two assertions a Step 7 run could dispute as PRD-silence rather than implementation defects**: `ERR_PETITION_STATUS_INVALID` chosen over `ERR_PENDING_OBJECTIONS` on a certify after an objection is filed, and delivery re-evaluating the Peerless Plywood blackout.

`workspace/implementation/` was never read, listed, or written, and `worklog.md` was not touched.

## Step 6: Generate Implementation — 2026-09-04T16:05:41Z

Implementation complete and verified. Smoke server (pid 2525355) confirmed as my own `python3 app.py` via `/proc/2525355/cmdline`, killed by that pid alone, and port 18730 verified free — no broad kill was used at any point.

## Deliverable

`workspace/implementation/` — 26 files, 3471 lines, `python3 -m compileall` clean, **exactly 66 routes** registered (matches the PRD endpoint table 1:1).

Layout: `app.py` (13 blueprints + error handlers), shared core in `auth.py`, `calc.py`, `clockutil.py`, `envelope.py`, `errors.py`, `gates.py`, `store.py`, `validate.py`, and 13 route modules under `routes/` (petitions, classifications, agreements, voter_lists, entries, supervisors, communications, rounds, sessions, ballots, objections, charges, clock). `start.sh` guards the pip install behind an `import flask` probe so the per-test reboot loop under 8 concurrent rounds doesn't thrash, then `exec python3 app.py` on `$PORT`.

Storage is Python dicts in `store.py`, empty on every boot; a grep for `sqlite|shelve|pickle|open(|json.dump(|/tmp` across all sources returns nothing. No entity is seeded, preloaded, or hardcoded.

## Real bug found and fixed

`post-tally` returned `ERR_INVALID_REQUEST` / "Unexpected server failure." because `clockutil.business_deadline()` returns a `datetime`, which I assigned raw to `objection_window_close_at`, so `json.dumps` raised. Fixed in `routes/rounds.py:114` by wrapping in `clockutil.fmt_dt(...)`, then hardened twice: `envelope._json_default` now serializes stray `datetime`/`date`/`Decimal` values instead of 500ing, and the fallback handler calls `app.logger.exception(...)` so any future crash leaves a traceback. Grep-audited every other `business_deadline` / `add_days` / `add_hours` / `add_minutes` / `end_of_day` call site — all were already `fmt_dt`-wrapped.

## Verification

~140 end-to-end assertions across two smoke passes, 0 real failures. Every worked example in the PRD reproduces exactly: voter-list deadline `2026-08-24T23:59:59Z`; location occupancy boundary (start at +29 min conflicts 409, at exactly +30 min succeeds 201); objection window `2026-09-14T23:59:59Z` skipping Labor Day; COI TRADITIONAL 67.00 / OVERWHELMING 53.50 / ACCRETION 65.50 with the core wage frozen at 2400 across later scoring calls; certification `CERTIFICATION_OF_REPRESENTATIVE` with year-end and decert at `2027-09-15T09:00:00Z` and the disjoint bar/bargaining-end fields correctly absent.

The second pass covered the paths not yet exercised: the full rerun arc (non-determinative SUSTAIN → 409, OVERRULE returning `OBJECTIONS_PENDING`→`TALLY_POSTED` only at count 0, determinative SUSTAIN firing all four hops plus voter-list `SUPERSEDED`, `schedule-rerun` minting round 2 with `prior_round_id` set); the blocking-charge cascade on a SCHEDULED round (round `SUSPENDED`, sessions `CANCELLED`, `scheduled_session_count` zeroed, posture `BLOCKED` with `case_status` untouched, then DISMISS restoring posture `OPEN` and round `SCHEDULED` while the cancelled session stays cancelled — the partly-reversible cascade); union-loss `CERTIFICATION_OF_RESULTS` with `election_bar_end_at` at +365d and the other four timeline fields null; and the Peerless Plywood 24-hour blackout beating the risk-score gate on `submit-for-review`. Ballot conservation held (`ballots_cast_total` pinned across resolve/reopen/re-resolve), private keys `_counted_blocking` and `_last_reviewed_at` never serialize, and `PlantSupervisor` self-scoping returns 403 on a foreign filter and implicitly self-filters when absent.

Constraints honored: `test_helpers/`, `test_suite/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, and `SCAFFOLD_CORNER_DESIGN.yaml` were never read, listed, globbed, or grepped; all files were written with chunked heredoc appends and verified with `ls -la` + `wc -l`; `worklog.md` was not touched.

**Orchestrator note on Steps 5/6 concurrency:** the two Agent calls were issued in back-to-back messages rather than one, so physical isolation of `test_suite/` from the impl generator rested on the ~40s gap plus an explicit hard prohibition in the Step 6 prompt. The impl agent's exit report confirms it never read, listed, globbed, or grepped `test_helpers/` or `test_suite/`. No strays under `workspace/`: `test_helpers/` and `test_suite/` both landed at the task root as required.

## Step 7: Run Tests and Iterate — 2026-09-04T16:56:55Z

Clean 8-round sweep. All 8 parallel rounds passed 283/283.

## Summary

**Iterations run:** 2

**Iteration 1** — 8/8 rounds at 282/283, with the *same single test* failing deterministically in every round (so not a load/flake artifact):
`test_rule_priority_and_boundaries.py::test_captive_audience_delivery_in_the_blackout_reports_the_per_se_violation_not_the_closed_period`
→ `Expected error_id ERR_PEERLESS_PLYWOOD_WINDOW, got ERR_CAMPAIGN_PERIOD_CLOSED`

**Iteration 2** — 8/8 rounds at 283/283, zero failures, zero errors.

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:** none.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes/communications.py`, `deliver_communication` — added a fresh evaluation of the per-se blackout rule via the existing `calc.peerless_plywood_violation(message, polls_open_at)` helper, ordered before the `ERR_CAMPAIGN_PERIOD_CLOSED` campaign-window check.

**Diagnosis detail (why this was an implementation bug, not a test bug):**

The handler previously consulted only two things: the *stored* `peerless_plywood_violation` flag, and whether the *logical clock* sat inside the blackout. In the failing scenario the message is drafted, accuracy-reviewed and approved **before any election round exists**, so at accuracy-review time there is no `polls_open_at` and the stored flag is legitimately `false`; the round is created later by `stipulate`, and delivery is attempted at `2026-09-01T18:00:00Z` — after `polls_close_at`, hence outside the blackout by clock. Both existing checks therefore passed and the campaign-window check fired instead.

PRD coverage is verbatim and uniquely derivable on both layers:
- §2.11 item 14: "a captive-audience meeting inside the pre-poll blackout yields `ERR_PEERLESS_PLYWOOD_WINDOW` (422). This is checked on all three message-pipeline dispositions: submitting for legal review, dispositioning legal review, and confirming delivery." — item 14 precedes item 17 (`ERR_CAMPAIGN_PERIOD_CLOSED`).
- §2.11 collision paragraph names this exact scenario and its exact answer: "A captive-audience message whose planned delivery sits inside the blackout, submitted for delivery after the polls have already closed, reports `ERR_PEERLESS_PLYWOOD_WINDOW` (422) rather than `ERR_CAMPAIGN_PERIOD_CLOSED` (409)."
- §3.7 defines the rule on `planned_delivery_at` (not on the clock): true when channel is `CAPTIVE_AUDIENCE_MEETING` and `planned_delivery_at` falls in the 24h before the current round's `polls_open_at`. Test setup: `polls_open_at` `2026-09-01T06:00:00Z`, `planned_delivery_at` `2026-09-01T05:00:00Z` — inside the window.

The pre-existing clock-based check was left in place (§3.7 separately requires "the logical clock not sit inside the current round's captive-audience blackout"), so no PRD-required check was weakened. The change was scoped to `deliver` only; the two other dispositions already read the stored flag and their tests pass, and re-evaluating there is not something the PRD's collision prose pins down.

Note: the 8 `results.$i.json` files from the final clean sweep are left in `workspace/implementation/` as evidence. `worklog.md` was not touched.

**Orchestrator verification:** independently re-read all 8 `results.$i.json` (86 KB each, all written 16:48) — every round reports `passed=283 total=283 failed=0 errors=0`. Sweep artifacts confirmed present, not merely claimed. Step 8 will therefore run (1 implementation fix > 0).

## Step 8: Finalize PRD — 2026-09-04T17:06:08Z

PRD_FINALIZED.md produced with two surgical edits.

**Size:** PRD.md 494 lines / 112,629 B → PRD_FINALIZED.md 494 lines / 113,372 B (lines +0.0%, bytes +0.66%). Verified complete via full `fold`-diff: only the two intended paragraphs differ.

**Changes**

- §3.7 (campaign-message delivery paragraph) — revise — inserted the per-se blackout layer into delivery's requirement list: delivery requires both that the stored `peerless_plywood_violation` flag be false **and** that the per-se rule, re-evaluated at delivery against the round then in force, not fire, so a captive-audience message whose `planned_delivery_at` sits inside that round's blackout is refused with `ERR_PEERLESS_PLYWOOD_WINDOW` even when the stored flag is false because no round existed at accuracy-review time. Existing clauses (posture, clock-in-blackout, campaign window) kept verbatim — `implementation/routes/communications.py:256-264`.
- §2.11 item 14 — revise — appended that submit-for-review and legal-review disposition consult the *stored* flag exactly as the accuracy review left it, while confirming delivery consults the flag *and additionally* re-evaluates the rule — `implementation/routes/communications.py:178, 213, 256-264`.

**Pre-edit search log**

Edit 1 (§3.7 delivery)
- (a) Subject: when and against what the per-se captive-audience blackout is evaluated at the delivery disposition, and how it layers with posture / clock / campaign-window.
- (b) Enumerated and read: `grep -rn "peerless" --include=*.py` (only two files touch it) → `calc.py:239-251` (`in_peerless_window` closed-lower/open-upper, `peerless_plywood_violation` channel-gated on `planned_delivery_at`); `routes/communications.py:78` (flag initialised false at draft), `:146-149` (accuracy review is the *only* writer, uses `_current_polls_open_at` = `store.current_round`), `:178` (submit-for-review, stored flag only), `:213` (legal review, stored flag only), `:243-273` (deliver: posture → status → stored flag → fresh re-eval → clock-in-window channel-gated → campaign window); `gates.py:31-36` (`require_open_posture`, runs first, matching collision 4); `store.py:127-132` (`current_round` = highest `round_number`); `store.py:99` + cascade callers (message BLOCKED transitions never write the flag).
- (c) Adjustment: scoped the re-evaluation claim to the *delivery* disposition only (the other two dispositions do not re-evaluate) and said "the round then in force" rather than naming a specific round-selection rule, so the sentence stays consistent with `store.current_round` and with the no-round case. Deliberately left the pre-existing clock-in-blackout clause verbatim rather than adding the impl's `CAPTIVE_AUDIENCE_MEETING` gate on it, since Step 7 exposed no mismatch there and a narrowing edit would be out of scope.

Edit 2 (§2.11 item 14)
- (a) Subject: what "checked on all three message-pipeline dispositions" means operationally — stored flag vs fresh evaluation.
- (b) Enumerated and read the same set: `routes/communications.py:178` and `:213` (both `if message["peerless_plywood_violation"]`, no recomputation), `:256-264` (flag plus fresh `calc.peerless_plywood_violation`), `:146-149` (sole writer), `calc.py:247-251`; confirmed no other module reads or writes the flag or recomputes `risk_score`.
- (c) Adjustment: phrased the first two as "consult the stored flag exactly as the accuracy review left it" instead of "never re-evaluate", and pointed to §3.7 for the delivery detail rather than restating the window arithmetic, keeping item 14's relative ordering (before item 17) and the collision paragraph untouched.

**Orchestrator verification:** PRD_FINALIZED.md exists, 494 lines / 113,372 B, and is NOT byte-identical to PRD.md — the edits landed.

## Step 9: Complete PRD — 2026-09-04T17:39:00.000Z

Run as **three sequential passes partitioned by implementation module**, all editing one shared `workspace/PRD_COMPLETED.md`. Pass 1 performed the `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2 and 3 edited in place additively and were explicitly forbidden to re-copy or revert. Total **62 edits — 49 ambiguity-pins, 13 mismatch-revisions**. File grew 113,372 B → 136,278 B (+20.2%) with the line count unchanged at 494, confirming every edit was in-paragraph and no section was added.

### Pass 1 — core modules + petitions/classifications/agreements/clock (22 edits: 19 pins, 3 mismatches)

Slice: `app.py`, `auth.py`, `envelope.py`, `errors.py`, `store.py`, `validate.py`, `gates.py`, `clockutil.py`, `calc.py`, `routes/common.py`, `routes/petitions.py`, `routes/classifications.py`, `routes/agreements.py`, `routes/clock.py`.

- §2.2 — insert — ambiguity — `api_request_id` is `req_` plus exactly twenty uppercase-alnum characters — envelope.py:14-15
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from real wall clock, the only response instant that does; everything stored/derived uses the logical clock — envelope.py:18-25
- §2.3 — insert — ambiguity — a non-integer `limit`/`offset` is the same `ERR_INVALID_REQUEST` as an out-of-range one — validate.py:137-152
- §2.3 — insert — ambiguity — identical `created_at` ties break by insertion order; out-of-enum filter values are 422, identifier filters matching nothing yield an empty page — store.py:56-58, validate.py:156-166
- §2.4 — insert — ambiguity — every server-computed instant other than `created_at`/`updated_at` renders to whole seconds, with 3 fractional digits only when non-zero sub-second data exists — clockutil.py:64-71
- §2.4 — insert — ambiguity — `current_utc` required and `Z`-offset; clock call answers 200 with empty `data`, may move backwards, no other gate — routes/clock.py:13-19
- §2.5 — revise — **mismatch** — "Nine operations sit behind that gate" → thirteen, adding open-scope-analysis, verify-showing (non-dismissal branch), stipulate, direct-election; complement list extended with the ungated classification/agreement ops — petitions.py:106,140; agreements.py:101,148
- §2.8 — revise — **mismatch** — `majority_threshold` removed from the two-decimal list and restated as an exact integer — calc.py:281-283
- §2.11 step 5 — insert — ambiguity — undeclared body fields ignored; absent/empty body read as `{}`; non-object or unparseable body fails here — validate.py:15-25
- §2.11 step 11 — revise — **mismatch** — "nine" → "thirteen" election-advancing operations — gates.py:31-37
- §2.11 step 12 — insert — ambiguity — target row's own state code outranks the parent case's `ERR_PETITION_STATUS_INVALID` — classifications.py:135-140, agreements.py:102-107
- §2.11 closing note — insert — ambiguity — `ERR_INVALID_TIME_WINDOW` is evaluated inside step 5, before path resolution (so it beats the 404) — agreements.py:97-99, validate.py:122-130
- §3.1 — insert — ambiguity — adding a classification is gated on neither `case_status` nor `case_posture` (allowed while `RECEIVED`) — classifications.py:22-41
- §3.2 — insert — ambiguity — scoring has no state precondition and may be repeated, overwriting the four derived fields, even on a ruled/`MOOT` row — classifications.py:99-122
- §3.2 — insert — ambiguity — the core-wage freeze mutates the petition, so its `version`/`updated_at` advance on the first scoring call only — classifications.py:110-112
- §3.2 — insert — ambiguity — reconsideration leaves `coi_score`, `wage_proximity`, `scoring_standard`, `coi_recommendation` untouched — classifications.py:182-183
- §3.3 — insert — ambiguity — a case with no classifications satisfies the all-ruled test vacuously → basis `AS_RULED`, denominator `included_headcount` — calc.py:136-141
- §3.3 — revise — ambiguity — the dismissal branch also writes `showing_headcount_basis` and the five card counts — petitions.py:151-159
- §3.3 — insert — ambiguity — a request yielding no verdict (negative valid cards / zero denominator) is gated as the non-dismissal branch, so `ERR_CASE_POSTURE_BLOCKED` precedes the arithmetic error — petitions.py:139-149
- §3.4 — insert — ambiguity — opening the arrangement file is gated on neither case dimension — agreements.py:22-33
- §3.8 ¶1 — insert — ambiguity — full initial field set of a newly created round (counters at 0, `provisional_margin` 0, revised/tally/window fields absent, both booleans false) — gates.py:208-244
- §3.9 — insert — ambiguity — the rerun builds on the highest-numbered `SET_ASIDE` round (falling back to the highest-numbered round of any status) and inherits its `election_agreement_id` — petitions.py:186-195

### Pass 2 — voter_lists / entries / supervisors / communications (20 edits: 15 pins, 5 mismatches)

- §2.1 — revise — mismatch — `PlantSupervisor` bullet claimed read access to messages they present; the single-message read does not admit the role, so only the *listing* reaches them and a single read is `ERR_ROLE_NOT_PERMITTED` — routes/communications.py:18
- §2.1 — insert — ambiguity — omitting the self-filter is served with the caller's own `X-User-ID` substituted; `petition_id`/`status` filters honoured as given — routes/communications.py:108-112
- §2.7 — revise — ambiguity — both existence checks (petition *and* `election_agreement_id`) precede the version comparison; the stale-version rejection outranks case coherence, the supersession sweep and the duplicate test — routes/voter_lists.py:28-34
- §3.5 ¶1 — insert — ambiguity — initial field set of a new list (0/false/absent); a rejected duplicate create disturbs no sibling; `REJECTED`/`SUPERSEDED`/`CANCELLED` siblings neither block nor are touched; no `case_status`/`case_posture`/agreement-status precondition, so `due_at` may be absent and the deadline/lateness tests then vacuous; only the petition is touched — routes/voter_lists.py:36-66
- §3.5 ¶2 — insert — ambiguity — `total_entry_count`/`complete_entry_count`/`eligible_voter_count` are recomputed while `completeness_pct`/`is_late`/`list_grade` are not; entry writes carry no status/posture/case_status precondition; version-bump pattern (parent always touched; entry stays at 1 on create) — routes/entries.py:34-57, gates.py:67-75
- §3.5 ¶2 — insert — ambiguity — PATCH null semantics: omitted field unchanged, explicit JSON `null` clears the field (raising `missing_field_count`; `on_leave_type` goes absent, not back to `NONE`) — routes/entries.py:105-107
- §3.5 ¶3 — insert — ambiguity — `INCLUDED`/`MOOT` classifications match neither rule one nor rule five; rule three vacuous when the arrangement has no `approved_election_date` — calc.py:154-172
- §3.5 ¶4 — insert — ambiguity — `ERR_VOTER_LIST_EMPTY` pinned after the two state preconditions and ahead of `ERR_VOTER_LIST_PAST_DUE` — routes/voter_lists.py:106-114
- §3.5 ¶5 — revise — **mismatch** — an `ACCEPT` closing a cure cycle *retains* `cure_window_hours`/`cure_deadline_at` (impl touches neither); `noted_defects` written on ACCEPT only when supplied — routes/voter_lists.py:170-177
- §3.5 ¶5 — insert — ambiguity — `noted_defects` is an unvalidated array of strings (empty array accepted) — routes/voter_lists.py:158
- §3.5 ¶5 — insert — ambiguity — `RETURN_FOR_CURE` and `REJECT` write `noted_defects` unconditionally, so omitting them clears prior codes — routes/voter_lists.py:185,194
- §3.5 ¶5 — insert — ambiguity — `REJECT` leaves `cure_deadline_at` as it stands rather than clearing it — routes/voter_lists.py:192-195
- §3.5 ¶6 — insert — ambiguity — resubmission consults neither `case_status` nor `case_posture`; overwrites `submitted_by_user_id`/`attested_by_title` and leaves `reviewed_at`/`noted_defects`/`cure_window_hours`/`cure_deadline_at` untouched — routes/voter_lists.py:125-150
- §3.6 ¶2 — insert — ambiguity — `modules_completed` only array-of-strings checked (extra codes neither rejected nor credited, empty array accepted); training gated on neither case dimension — routes/supervisors.py:82,89-91
- §3.6 ¶2 — revise — **mismatch** — a failed attempt records score *and* module list, not only the counter; a failing attempt never demotes a `TRAINED` supervisor and a qualifying attempt by one is a self-loop re-stamping `certified_at` — routes/supervisors.py:86-93
- §3.6 ¶3 — insert — ambiguity — an unsubstantiated finding is a complete no-op (no counters, no `version`/`updated_at` advance) — routes/supervisors.py:106-107
- §3.6 ¶3 — revise — **mismatch** — hop one of the three-hop cascade runs unconditionally; an already-`UNTRAINED` supervisor still gets `violation_count`/`last_violation_code` but neither later hop — routes/supervisors.py:110-118
- §3.6 ¶3 — insert — ambiguity — the petition is touched only when `retraining_required` actually flips — gates.py:144-146
- §3.7 ¶1 — revise — ambiguity — `presenter_supervisor_id` presence/absence is enforced as `ERR_INVALID_REQUEST` both ways, at step 5 ahead of reference resolution — routes/communications.py:50-54
- §3.7 ¶1 — insert — ambiguity — the two claim counters are non-negative and are *not* cross-checked at draft time — routes/communications.py:45-48
- §3.7 ¶2 — insert — ambiguity — the presenter slot is held by every existing meeting-channel message with that presenter in *any* status (incl. `BLOCKED`, `DELIVERED`); non-meeting messages hold none; the check precedes insertion — routes/communications.py:89-100
- §3.7 ¶3 — insert — ambiguity — accuracy review has no status precondition and no posture gate, is freely repeatable, recomputes from scratch, leaves `status`/`revision_round`/`escalation_ack`/`reviewed_by_user_id`/`blocked_reason` alone, and reads `polls_open_at` from the highest-numbered round — routes/communications.py:131-151, :21-25
- §3.7 ¶8 — revise — ambiguity — `review_note` validated then discarded; the elevated-score gate reads *this request's* `escalation_ack` (never the stored value); the field is written only when supplied, on both branches — routes/communications.py:206-231
- §3.7 ¶8 — revise — **mismatch** — the per-se blackout test runs before the branch, so `REQUEST_REVISION` is refused too — routes/communications.py:213-215
- §3.7 ¶9 — revise — ambiguity — the clock-blackout test at delivery applies to `CAPTIVE_AUDIENCE_MEETING` alone; `polls_close_at` is strict; a case with no round at all is `ERR_CAMPAIGN_PERIOD_CLOSED` — routes/communications.py:265-273

### Pass 3 — rounds / sessions / ballots / objections / charges (20 edits: 15 pins, 5 mismatches)

- §3.8 (session layout) — insert — ambiguity — cancelled sessions release their polling location; only `SCHEDULED`/`CLOSED` sessions occupy one, so a replacement may reuse the exact window — routes/sessions.py:45
- §3.8 (observers) — revise — **mismatch** — the role/party pairing is descriptive only; `party` comes from the body and is never compared against the acting role, so any of the three roles may seat either party's observer — routes/sessions.py:96,112 + auth.py:42
- §3.8 (observers) — insert — ambiguity — designation is gated on neither the session's nor the round's status; an observer may be seated on a `CLOSED` or `CANCELLED` session — routes/sessions.py:100
- §3.8 (open polls) — insert — ambiguity — a round with `scheduled_session_count` 0 is refused with `ERR_ROUND_STATUS_INVALID`, and that test runs *after* the accepted-list test, so a round missing both reports `ERR_VOTER_LIST_NOT_ACCEPTED` — routes/rounds.py:68-74
- §3.8 (open polls) — insert — ambiguity — a clock exactly equal to `polls_open_at` counts as reached — routes/rounds.py:76
- §3.8 (open polls) — insert — ambiguity — opening moves neither `case_status` nor `case_posture` — routes/rounds.py:80-82
- §3.8 (close session) — insert — ambiguity — the posture gate is applied to the case reached *through the session's round*; the four preconditions run in listed order, so a non-`SCHEDULED` session reports `ERR_POLL_SESSION_STATUS_INVALID` over the round's code, and a clock short of `session_end_at` also reports `ERR_POLL_SESSION_STATUS_INVALID` rather than a window code — routes/sessions.py:136-154
- §3.8 (polls closed) — revise — ambiguity — exact `ballots_cast_total` formula: three counts over `CLOSED` sessions plus `challenged_ballot_count` over **every** session on the round whatever its status; sums are re-derived, not accumulated — routes/sessions.py:166-174
- §3.8 (post tally) — revise — ambiguity — the `ERR_TALLY_RECONCILIATION_FAILED` comparison total uses that same rule — routes/rounds.py:20-28,99
- §3.8 (segregate ballot) — insert — ambiguity — segregation is gated on neither session nor round status — routes/ballots.py:39-76
- §3.8 (segregate ballot) — insert — ambiguity — the duplicate test spans every ballot at that session whatever its `resolution` (a withdrawn challenge still blocks); entry-less ballots are never compared — routes/ballots.py:53-56
- §3.8 (resolve ballot) — insert — ambiguity — on resolve and reopen alike the ballot's own state is tested before the round's, so `ERR_BALLOT_STATUS_INVALID` outranks `ERR_ROUND_STATUS_INVALID` — routes/ballots.py:110-113,135-138
- §3.8 (resolve ballot) — insert — ambiguity — a `withdrawing_party` mismatch is `ERR_INVALID_REQUEST` (422), tested after both state checks; one sent with the other three resolutions is enum-checked then ignored — routes/ballots.py:106-116
- §3.8 (reopen ballot) — revise — **mismatch** — `reopen_reason` is accepted and schema-checked but never stored or returned — routes/ballots.py:132
- §3.8 (revise tally) — insert — ambiguity — revising writes nothing to the petition, so `case_status` stays at `TALLY_POSTED` or `OBJECTIONS_PENDING` — routes/rounds.py:126-155
- §3.9 (file objection) — revise — **mismatch** — *any* objection filed while `case_status` reads `TALLY_POSTED` moves it to `OBJECTIONS_PENDING`, not merely the first; every other status is left alone — routes/objections.py:64-65
- §3.9 (rule objection) — insert — ambiguity — determinativeness is tested before the round-status check, so `ERR_OBJECTION_NOT_DETERMINATIVE` outranks `ERR_ROUND_STATUS_INVALID` — routes/objections.py:107-114
- §3.9 (overrule) — insert — ambiguity — `pending_objection_count` never drops below 0, and overruling requires no round status, so a `SET_ASIDE` round's objection may still be overruled — routes/objections.py:136-138
- §3.9 (sustain cascade) — revise — **mismatch** — **every** `ACCEPTED` voter list on the case is superseded, not just one — gates.py:152-155
- §3.9 (docket charge) — insert — ambiguity — a blocking request on a `DISMISSED`/`CERTIFIED` case stores `blocking_requested` true but is never counted, runs no cascade, and its later dismissal/settlement leaves `blocking_charge_count` untouched — routes/charges.py:45-46,129,163
- §3.9 (determine charge) — revise — **mismatch** — `notice_posting_end_at` is written only when `notice_posting_days` was supplied (0 included, landing on `determined_at`); `notice_posting_days` recorded under either determination while `remedy_code` is stored only on the merit path; `RERUN_ELECTION` drives nothing — routes/charges.py:114-135
- §2.11 step 26 — revise — **mismatch** — `ERR_OBSERVER_CAPACITY_EXCEEDED` also fires as a close-session precondition, not only on designation — routes/sessions.py:151-154

### Pass-3 hand-off verifications that needed no edit
- `blocking_charge_cascade` blocks only `APPROVED`, so `POSTURE_BLOCKED` is reachable only from `APPROVED` — §3.9 already states exactly that, and `unblock_chain`'s restoration to `APPROVED` is already pinned. §3.7's "blocked out of `PENDING_LEGAL_REVIEW` keeps `revision_round`" is consistent, reachable via `RERUN_BLACKOUT`, `PRESENTER_DECERTIFIED` and `CASE_DISMISSED` only.
- §3.9's rerun cascade prose is already explicit by enumeration ("`APPROVED` or `PENDING_LEGAL_REVIEW`"), so it uniquely determines that `DRAFT` and `REVISION_REQUIRED` are untouched.
- The §5 error catalogue matches `errors.py:3-80` exactly.

### Orchestrator verification
`PRD_COMPLETED.md` is 494 lines / 136,278 bytes; **not** byte-identical to `PRD_FINALIZED.md` (so the scan genuinely ran); all five top-level sections present at lines 3 / 11 / 174 / 340 / 413; file ends on the complete final row of the §5 error table. Step 9 edited documentation only — no `implementation/`, `test_suite/` or `test_helpers/` file was touched, so the clean 8-round sweep recorded in Step 7 remains valid and the `results.{1..8}.json` evidence files are unchanged.

Pipeline complete.
