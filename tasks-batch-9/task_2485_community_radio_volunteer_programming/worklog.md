# Worklog — task_2485_community_radio_volunteer_programming

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2485_community_radio_volunteer_programming/` and its `workspace/` subdirectory. Index 2485 was pre-assigned by the orchestrating pipeline; no scan of `./tasks/` was performed (concurrent pipelines on this host would collide).

## Step 2: Generate scaffold — 2026-09-03T01:22:00.000Z

All three scaffold artifacts are complete and lint-clean in `/home/ubuntu/github/CodingPRD/tasks/task_2485_community_radio_volunteer_programming/`.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2485_community_radio_volunteer_programming/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2485_community_radio_volunteer_programming/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2485_community_radio_volunteer_programming/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    78
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     67
  Calls scanned (§1.8+§1.9):  1088

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**SCAFFOLD.yaml** (3280 lines, §1.0–§1.7 only — no design keys): scenario verbatim, `api_prefix: ""`, 15 entities, 12 state machines, 4 concurrency rules, 8 calculations, 56 validations, 78 endpoints, 66 errors, 6 roles. Profile: primary archetype `multi_party_negotiation`, secondary `temporal_windowing`, layers `optimistic_concurrency / cascading_side_effects / dual_variant_calculation / rate_threshold_triggers`, flat topology, cyclic state machines, `segregation_of_duties` role model, `immediate` consistency.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (1017 lines): all 9 Difficulty Rules × 2 = 18 instances, each with the full seven-point `test_recipe` and author-computed literals (e.g. royalty 529 vs 481 survey/census, performance 100.00 vs 92.14, seniority cap 70.00 not 101.00, PA share exactly 8.00%, 5-point preempt margin).

**SCAFFOLD_CORNER_DESIGN.yaml** (2366 lines): 85 instances across all nine §1.9 sections — 67 with full test recipes, 18 `excluded_because` stubs that each cite an existing §1.8 instance by name. Per section (total/stubs): entities 13/0, state_machines 13/2, calculations 12/6, validations 12/3, endpoints 6/1, errors 8/1, rbac 9/1, cross-cutting complexity layers 10/3, consistency model 2/1. All four `concurrency_rules` entries get their own OCC stale-version test.

Verification beyond the linter (the linter checks neither of these): no duplicate `name` across the union of both design files; every `excluded_because.difficulty_instance` resolves to a real §1.8 instance name and no stub carries a `test_recipe`; every `${placeholder}` in each recipe resolves to a capture made earlier in that same recipe; no nested-list `setup_api_calls` (two OCC instances were restructured to move the interleaving writes into `trigger`); every `claim_type` traces to a row of the claim-extraction guide for that section, including the algorithm-type rows now that each calculation's declared type was cross-checked. One spec-fidelity fix to SCAFFOLD.yaml: the calculations key `algorithm_type:` was renamed to `algorithm:` (8 occurrences) to match the §1.3 template; no design file referenced the old key name.

Size was managed with YAML anchors — three whole-sequence anchors (`k_chain_open_review` 11 calls, `k_chain_grid` 18, `k_chain_episode` 21) plus ~25 individual call anchors — so a full-chain instance costs one line.

## Step 3: Copy shared files — 2026-09-03T01:23:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T01:43:00.000Z

PRD generation is complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2485_community_radio_volunteer_programming/workspace/PRD.md`

**Size and structure**
- 560 lines, ~16,360 words
- 5 top-level sections, 21 subsections: §1 Introduction; §2 Global Specifications (2.1–2.12); §3 Business Logic (3.1–3.9); §4 Endpoint Definitions; §5 Error Code Catalogue
- §2 subsections: RBAC, response structure (verbatim block), pagination, logical clock, common/immutable record properties, path resolution, numbers & rounding, version guards, two-dimensional state & cascade discipline, order of refusal (14-rung ladder), conserved totals, daily sweep
- §3 subsections: certification; seniority/strikes/discipline; proposals & committee; grid construction & publication; airings, playlist logs & royalties; underwriting copy, political content & public file; incidents, penalty points & standing; performance review, probation & cancellation; drives, phone banks & premium fulfilment
- §4 is a 4-column table with all **78** endpoints (verified 80 table lines = 78 + header + separator); §5 is a 2-column table with all **66** errors (68 lines)
- File ends at a real boundary — the last `ERR_POLITICAL_COPY_UNCENSORABLE` table row; no `<!-- CONTINUE -->` sentinel remains

**Hard Contract verification** (scripted against SCAFFOLD.yaml, not eyeballed)
- **Contract 1 — Field-Name Coverage: PASS.** All 154 `entities[].fields[].name` values and all 100 distinct endpoint `input` identifiers (request bodies, query params) appear verbatim in backticks. Zero missing.
- **Contract 2 — Rule Coverage: PASS.** All 66 `error_id` values present; all 56 `validations` rules represented with their relative priority order rendered in §2.10 (spot-checked against scaffold priorities: 45 segregation before 50 state; 50 grid-mutable before 66 slot-conflict; 68 cooling-off before 69 attempt cap; 72 grid-empty → 73 tentative → 74 diversity; 66 slot-conflict before 77 seniority margin). All state-machine states (initial, terminal, every `from`/`to`) present; all field-constraint enum values present; all 6 roles present. All 8 calculations documented in prose with rounding placement made explicit.
- **Contract 3 — §3 Path Purity: PASS.** No backticked token in §3 (lines 189–401) begins with `/`, is a bare HTTP method, or combines method+path. Paths appear only in §2.8 (permitted) and §4.

**Additional style checks:** no pseudocode symbols anywhere (`==`, `>=`, `<=`, `!=`, `+=`, `min(`, `max(`, `round_half_up`, `&&`, `||` all absent); no fuzzy quantifiers ("approximately", "roughly", "conservatively", "as needed").

**Two mid-drafting corrections made against the scaffold:** the air-result input is `air_status` (not an `outcome` field), and `PATCH /underwriting-spots/{spotId}` does not accept `underwriter_name` — the PRD now states the sponsor name is fixed at drafting, which is also load-bearing for the `MISSING_SPONSOR_ID` screen.

The withheld files `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

**Orchestrator truncation check (per pipeline instruction):** independently verified — `tail -12 PRD.md` ends with the complete table row `| \`ERR_POLITICAL_COPY_UNCENSORABLE\` | 422 |`, a real section boundary, not mid-sentence. No regeneration needed.

## Step 6: Generate implementation — 2026-09-03T02:35:00.000Z

(Launched concurrently with Step 5; Step 6 returned first, so it is logged first. Step 5's entry follows.)

Implementation complete and smoke-verified. Isolation constraint held throughout — nothing under `test_helpers/`, `test_suite/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml` was read, listed, globbed or grepped. Built strictly from `INSTRUCTION.md` + `SCAFFOLD.yaml` + `PRD.md`.

## Files written
All under `workspace/implementation/`:

- `start.sh` — guarded launcher (`pip install` only when Flask is missing, then `exec python3 app.py`); binds `0.0.0.0:$PORT`, default 10000
- `requirements.txt` — `Flask>=2.2`
- `app.py` — app factory, route registration, `ApiError`/`HTTPException`/catch-all handlers
- `db.py` — logical clock (default `2026-08-01T00:00:00Z`), 15 in-memory dicts, per-request dirty-set version bookkeeping, calendar math
- `errors.py` — full PRD §5 catalogue (400/403/404/409/412/422) + `ApiError`
- `response.py` — envelope, Decimal-exact JSON (so `54.00` renders with both decimals), `req_`-prefixed request ids, pagination
- `middleware.py` — auth (6 roles), field validators, path lookups; module docstring records the 14-rung Order of Refusal
- `services/` — `calc.py` (all arithmetic), `domain.py` (state machines + cascades), `records.py`, `serializers.py`
- `routes/` — `operations`, `volunteers`, `proposals`, `programs`, `schedule`, `episodes`, `underwriting`, `development`

**78 endpoints registered — exactly matching the 78 rows in the PRD §4 table** (verified by counting `app.url_map` against the table).

## Verification
Wrote a ~140-assertion in-process smoke script (scratch only) covering the full spine: enrolment → certifications → proposal → committee ballots → decide → grid → slots → publish → episodes → playlist → log certify → performance review → underwriting review → incident adjudicate/remediate → drives/shifts/premiums/pledges → daily sweep → envelope/auth/pagination/404s. **All pass.** Also confirmed a fresh `bash start.sh` boots over real HTTP with a completely empty store, and killed all scratch servers afterward.

## Bugs found and fixed during verification
1. **`seniority_score` was derived live; the PRD makes it stored.** §3.1 pins a new volunteer at `0.00` regardless of how far back `seniority_start_date` reaches, and §3.2 names exactly five recompute triggers. Now stored, recomputed on status change, a certification reaching PASSED/EXPIRED/REVOKED, a `strike_count` change, and a hosted show's `performance_score` being rewritten. `continuous_service_months` / `current_certification_count` stay clock-derived per their literal definitions.
2. **`needs_core_renewal` was clock-based; the PRD defines it by record status** ("absent, `EXPIRED` or `REVOKED`"). It now only flips once the sweep has lapsed the record — which is what makes the sweep's "sets `needs_core_renewal` true" meaningful, and matches §2.12's rule that time alone moves nothing.
3. **`WARNING` sanction over-demoted.** It was sending any `CERTIFIED` respondent to `PROBATION`; §3.2/§3.7 demote only when the strike is the one that reaches two.
4. **Five missing list filters** vs. the §4 table: `programs?proposal_id`, `slot-assignments?preempted_by_program_id`, `episodes?slot_assignment_id&board_operator_volunteer_id`, `compliance-incidents?episode_id&underwriting_spot_id`, `pledges?premium_item_id`.

## Notable design decisions
- **In-memory only**, no seeding, no disk (`grep` for sqlite/open/pickle/shelve is clean). Store is empty on every boot.
- Version bumps are once-per-row-per-request via a dirty set committed inside the response helpers, so bumps land in the emitted body; error responses never commit.
- Derived-live where PRD definitions are event-equivalent: grid minutes/pct, program penalty points + standing, drive aggregates, premium status. Stored: `performance_score`, `composite_score`, episode featured/local counts, royalties, `seniority_score`.
- Rounding-order sensitivity honoured: SURVEY sums seconds then rounds once with the 1.10 uplift (529¢ on 185/212/47s); CENSUS rounds per entry then sums (481¢).
- Interval conventions kept deliberately different: slot collisions use the 2-minute changeover buffer, volunteer shift conflicts are **closed** intervals, phone-line capacity is **half-open** — all three confirmed by smoke assertions.
- Premium waterfall walks the ranking once and *does* fall through to a lesser stocked tier; `BACKORDERED` on the top-ranked candidate only when every candidate is out of stock (verified, including the compensating refund path restoring `on_hand_qty`).

## Step 5: Generate unit tests — 2026-09-03T03:44:00.000Z

(Launched concurrently with Step 6 in the same assistant message; returned second.)

Test suite generation for task 2485 is complete. Final collection: **102 tests, 0 collection errors** (`PYTHONPATH=. python -m pytest test_suite --collect-only -q`).

## Files

`test_helpers/` (9 files, written earlier, unchanged): `__init__.py`, `api_client.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, plus supporting modules.

`test_suite/` — `conftest.py` and 18 test modules:

| Queue | Files | Tests |
|---|---|---|
| A (Difficulty, §1.8) | `test_01_dual_variant_calc.py` … `test_09_compensating_invariant.py` | 36 |
| B (Corner, §1.9) | `test_10_entities.py` … `test_18_consistency_model.py` | 66 |

Written this session: `test_14_endpoints.py` (5), `test_15_errors.py` (7), `test_16_rbac.py` (8), `test_17_cross_cutting.py` (7), `test_18_consistency_model.py` (1). Earlier in the session: `test_11_state_machines.py` (11), `test_12_calculations.py` (6), `test_13_validations.py` (9).

## Coverage against the design indices

- **Queue A:** all 18 difficulty instances, exactly 2 tests each (36 tags, none under the two-test minimum).
- **Queue B:** 66 of the 67 non-stub corner instances, 1 test each — entities 12, state_machines 11, calculations 6, validations 9, endpoints 5, errors 7, rbac 8, cross-cutting complexity layers 7, consistency model 1.
- Every test carries exactly one `Design:` line; a mechanical audit resolved all 102 tags against `name:` values in the two yamls (no dual tags, no untagged tests, no dangling tags).

## Skipped

- **18 stub corner instances** — carry `excluded_because:` with no `test_recipe:`, so out of scope by construction.
- **`Corner/entities/volunteer_patch_with_invalid_payload_cannot_set_status`** — fails condition 2 of the PRD-first filter. The instance asserts `ERR_VALIDATION`, but PRD §3.1 uniquely derives the opposite outcome: "any of the computed fields present in such a payload is **ignored rather than honoured**". No placeholder or xfail emitted.

Three individual asserts were dropped (instance kept) where the yaml over-specified relative to the PRD: `approved_copy_text == copy_text` on an approved spot, `pledges_taken_count == 0` at shift creation, and `compliance_flags is null` on a patched draft spot — the last replaced with `== []`, since §3.6 says a new spot carries "an empty `compliance_flags` array".

## Final passes

- **PRD-citation pass:** every quoted passage in the new modules re-read verbatim from `workspace/PRD.md` (§2.8 stale-version rules, §2.10 rung ladder, §3.1 attempt cap and 80-point pass mark, §3.3 ballot domain/self-vote/weights, §3.4 occupation defaults and publication, §3.6 amendment scope, §3.7 penalty bases and standing bands, §3.9 waterfall and drive aggregates, §4 endpoint role lists).
- **Scaffold-citation pass:** zero occurrences of "scaffold", `SCAFFOLD_`, or any `§1.x` reference anywhere in `test_suite/` or `test_helpers/`.
- `python -m pyflakes` clean across both directories (no unused imports, no undefined names).

Isolation held throughout: nothing under `workspace/implementation/` was read or written, and no duplicate implementation agent was spawned.

## Step 7: Run tests and iterate — 2026-09-03T04:05:00.000Z

Verified independently: all 8 `results.*.json` written at 03:21:35 (after both edits at 03:16 and 03:18), each `102/102 passed, 0 failed, 0 errors`.

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each, 102 tests, `per-test-server` isolation).

Sweep 1: 87/102 in all 8 rounds — perfectly deterministic, 15 identical failures, zero flakiness. Sweep 2 (after fixes): 102/102 in all 8 rounds.

**Tests deleted:** none. Both failure clusters traced to real defects, and every asserted rule was verbatim in PRD.

**Fixes applied to `test_helpers/`**

- `test_helpers/assertions.py` — `_normalise_instant()`. The fraction was sliced with `tail[:6]`, which ran past the fractional digits and swallowed offset characters after `Z` was rewritten to `+00:00`, so `2026-02-20T12:00:00.000Z` normalised to the malformed `2026-02-20T12:00:00.000+:00` and never compared equal to `2026-02-20T12:00:00Z`. Now the fraction is scanned digit-by-digit and the offset preserved intact. This was one upstream bug masquerading as 11 independent implementation bugs (fields `last_evaluated_at`, `public_file_due_at`, `published_at`, `expires_on`, `created_at`, `last_attempt_at`, `log_due_at`, `flight_start`).

  The helper's own docstring already declared the intent ("a whole-second instant is written either with or without a `.000` fraction; both denote one moment"), and PRD §2.5 pins `created_at`/`updated_at` as "an ISO 8601 UTC timestamp with three fractional digits" — so the implementation's `.000` rendering was correct and the comparison was broken. Tolerance is also the only defensible assertion for `flight_start`, a client-supplied instant echoed back, where normalising and verbatim-echoing are both PRD-faithful readings.

**Fixes applied to `implementation/`**

- `workspace/implementation/services/serializers.py` — `_common()`. The deferred version-bump `commit()` lived inside `response.obj()`, but the uniform route pattern is `return response.obj(ser.X(row))`, and Python evaluates the serializer argument *before* calling `obj()`. Every successful mutation therefore emitted a body one version behind (`version: 1` after a first mutation, stale `updated_at`), even though the stored row was correct — visible only on a follow-up GET. `commit()` now runs at the top of `_common()`, the single choke point every versioned serializer passes through, so pending bumps land in the emitted body.

  PRD §2.5 verbatim: "`version` — an integer that starts at 1 on creation and increases by exactly 1 on every mutation of the row." Placing the commit on the serialization path (rather than making `touch()` bump eagerly) preserves the property that refusals never commit — an error response never reaches a serializer — which the "writes nothing" tests assert. This one fix resolved the remaining 4 failures (`version` on volunteer PATCH, certification retake, proposal open-review replay, drive activation).

No test was weakened, skipped, or xfailed; no implementation check was removed; storage remains in-memory with no seeded data.

**Orchestrator re-verification (per memory note on Step 7 sweep artifacts):** independently re-listed and parsed all 8 `results.N.json` on disk — every file present, each reporting `passed=102, failed=0, errors=0, total=102, skipped=0`. Clean sweep confirmed, not merely claimed.

## Step 8: Finalize PRD — 2026-09-03T04:20:00.000Z

`PRD_FINALIZED.md` is written. Both `<step_7_diff>` items produced exactly one PRD-silence pin each; both land in §2.5.

**Line counts:** PRD.md 560 → PRD_FINALIZED.md 564 (+4 lines, +0.71%). Two inserted paragraphs, zero existing lines revised or deleted.

**Changes**

- §2.5 (Common Record Properties) — *insert* — version/`updated_at` move at most once per row per accepted request; multi-touch cascades coalesce into a single +1; a row created by the request stays on `version` 1 even if that same request changes it (cert opened + graded in one call returns `version` 1, `updated_at` == `created_at`); an amendment naming no amendable field leaves both untouched, while naming one advances them even if the value is unchanged; a mutated row appearing in its own request's body carries the post-mutation values — `implementation/db.py:106-116` (`commit()`), `implementation/services/serializers.py:9-21` (`_common()` calling `commit()` before the payload is built).
- §2.5 — *insert* — every emitted instant is rendered `YYYY-MM-DDTHH:MM:SS.mmmZ` in UTC with exactly three fractional digits (whole seconds get `.000`), client-supplied instants are normalised rather than echoed verbatim, sub-millisecond precision truncated, and `seniority_start_date` stays a bare `YYYY-MM-DD` — `implementation/response.py:42-57` (`iso`/`iso_date`).

**Pre-edit search log**

Edit 1 — subject: when and how often `version`/`updated_at` advance, and what the response body shows.
(b) Enumerated & read: `db.py:71-117` (`begin_request`, `new_row`, `touch`, `commit` — note `commit()` skips ids in `g.created` and bumps each dirty row once); `services/serializers.py` (all 15 serializers; `committee_vote` and `playlist_entry` are unversioned, matching §2.5's write-once exceptions); `response.py:85-96` (`obj`/`collection` also call `commit()`, so the sweep's array-only body still commits); grepped every `touch(` callsite in `routes/*.py` and `services/domain.py`. Multi-touch-same-row paths confirmed: `domain.restricted_cascade` (grid touched per preempted slot), `domain.release_program_slots`→`release_slot` (grid touched per release), `domain.publish_grid` (superseded grid touched, then again per released slot), `routes/schedule.py:171-194` (two incumbents preempted + grid), `routes/development.py:344-345/359-360` (pledge + drive). Created-then-touched paths: only `routes/volunteers.py:141-164` (`open_certification` with `exam_score` → `grade_exam` touches the freshly created row). No-op-amendment paths: all three PATCHes guard with `changed` — `volunteers.py:126-137`, `proposals.py:100-113`, `underwriting.py:113-124`, and all three set `changed` on field *presence*, not value difference.
(c) Adjustments: added "however many separate advances a later section describes for the steps inside it" so §3.4/§3.7's per-preemption / per-release phrasing is subsumed rather than contradicted (§2's own "unless a later section narrows it" would otherwise have let those read as +1 each). Scoped the body claim to "whenever a mutated row appears in the response body" rather than a universal "every mutation is echoed", because the daily sweep returns only id arrays. Dropped a drafted "a refused request mutates nothing" sentence — PRD already covers refusals and a universal claim risked mis-describing paths Step 7 never exercised.

Edit 2 — subject: the wire rendering of instant-valued fields (the field list in the `_normalise_instant` fixture bug).
(b) Enumerated & read: `response.py:42-49` (`iso`, sole instant formatter: always `%03d` ms + literal `Z`, `astimezone(utc)`, `microsecond // 1000` truncation, passes `str` through unchanged) and `response.py:52-57` (`iso_date`); grepped every `iso(`/`iso_date(` callsite — all 26 serializer instant fields plus `routes/operations.py:22` (`current_utc` echo) and `response.py:75` (`api_request_timestamp`, already pinned at three digits by §2.2); grepped `isoformat|strftime` repo-wide to confirm no second formatter; confirmed via `middleware.parse_moment`/`datetime_field` that every stored instant is a UTC-converted `datetime` (never a raw string), so the `str` passthrough branch is dead and "normalised, not echoed verbatim" holds for `flight_start`, `scheduled_start_utc`, `occurred_at`, `effective_from/to`, and drive/shift `start_at`/`end_at`.
(c) Adjustments: said "instant" throughout and added the explicit `seniority_start_date` carve-out, since it is the one date-shaped field rendered by `iso_date` — an unqualified "every timestamp field" would have wrongly promoted it to a full instant. Added the truncation clause (not rounding) to match `microsecond // 1000`.

## Step 9: Complete PRD — 2026-09-03T04:40:00.000Z

Verified and finished. `PRD_COMPLETED.md` is complete and terminates at a real section boundary (last line of the §5 error catalogue, `| ERR_POLITICAL_COPY_UNCENSORABLE | 422 |`).

## Metrics

| | PRD_FINALIZED.md | PRD_COMPLETED.md |
|---|---|---|
| lines | 564 | 568 |
| bytes | 119,159 | 139,345 (+20,186) |
| chars | — | +20,065 |

54 diff hunks carrying 62 pinned points: **51 ambiguity-pins, 11 mismatch-revisions**. No new sections (`##`/`###` counts identical); 2 new paragraphs only (the §2.5 derived-vs-stored inventory and the §3.6 review-ordering paragraph), everything else in-paragraph. §5 untouched; §4 touched only in three description cells.

## Changes

- §2.2 — revise — ambiguity — `api_request_id` is `req_` + 20 chars from uppercase letters and digits — `response.py:64,68`
- §2.2 — revise — ambiguity — `api_request_timestamp` reports the logical clock, never the host wall clock — `response.py:74`
- §2.3 — revise — ambiguity — a non-base-ten `limit`/`offset` is `ERR_VALIDATION`; empty/absent falls back to default — `response.py:119-126`
- §2.3 — insert — ambiguity — equal `created_at` ties broken by server write order — `db.py` `ordered()`
- §2.4 — revise — ambiguity — clock endpoint answers 200 with `data` whose single field is `current_utc`; malformed input is `ERR_VALIDATION` — `routes/operations.py:20`
- §2.5 — insert — ambiguity — full derived-at-read vs stored field inventory; a read-time recompute is not a mutation — `services/serializers.py:9-21`, `services/calc.py:429-434`
- §2.10 — insert — ambiguity — ownership rungs fall through to the collection's 404 when the record is absent; committee seating is decided before any lookup — `routes/proposals.py:186-188`
- §2.10 — insert — ambiguity — the three ownership errors are path-scoped, so the path 404 precedes them — `routes/volunteers.py:121`
- §2.12 — insert — ambiguity — sweep runs its four phases in order, walks each collection in listing order, fills arrays in that order — `services/domain.py` `daily_sweep`
- §3.1 — revise — ambiguity — duplicate `email` outranks `ERR_NOT_EDITABLE` on a `RESIGNED` row; 404 precedes both — `routes/volunteers.py:122-125`
- §3.1 — insert — ambiguity — no uniqueness on the (volunteer, `cert_type`) pairing — `routes/volunteers.py:149`
- §3.1 — insert — ambiguity — "first record" means none of any kind, and promotion fires only from `PROSPECT` — `routes/volunteers.py:148,160`
- §3.1 — insert — mismatch — `needs_core_renewal` is measured against record status alone, not the clock (deliberate asymmetry with `current_certification_count`) — `services/calc.py:92-98`
- §3.1 — revise — mismatch — revocation *re-derives* `needs_core_renewal` rather than setting it true, so revoking `UNDERWRITING_COPY` leaves it false; incident-support test precedes the record's state test — `routes/volunteers.py:253-259`
- §3.2 — insert — ambiguity — host-termination cascade does not send already-`CANCELLED` shows back to `APPROVED_UNSCHEDULED` — `services/domain.py` `revert_to_unscheduled_if_idle`
- §3.3 — insert — ambiguity — `language_code` accepts any two ASCII letters and is stored verbatim in the case supplied — `middleware.py:192-203`
- §3.3 — insert — ambiguity — `diversity_tags` must be an array of strings; `proposer_volunteer_id` must exist but needs no roster standing — `middleware.py:132-143`
- §3.3 — insert — ambiguity — submission only from `DRAFT`/`REVISION_REQUESTED`, state checked before proposer standing — `routes/proposals.py:120-135`
- §3.3 — revise — mismatch — five ballot refusals, with `ERR_SELF_VOTE_FORBIDDEN` ahead of `ERR_PROPOSAL_NOT_IN_REVIEW`; the seat test reads the caller, the rest read `member_volunteer_id` — `routes/proposals.py:186-192`
- §3.3 — revise — mismatch — language bonus compares `language_code` case-insensitively, so `en` earns nothing — `services/calc.py:168`
- §3.3 — insert — ambiguity — re-submission after a revision leaves `decided_at` standing — `routes/proposals.py:130-140`
- §3.3 — insert — ambiguity — the tally answers with the decided proposal at 200; a created show is read separately — `routes/proposals.py:285`
- §3.4 — revise — mismatch — the seniority margin is all-or-nothing across *every* colliding incumbent; an absent host counts as `0.00` — `routes/schedule.py:171-180`
- §3.4 — insert — ambiguity — the week cap is measured before preemption returns minutes, and sits between the two collision outcomes — `routes/schedule.py:164-169`
- §3.4 — insert — ambiguity — `ERR_PROGRAM_RESTRICTED` outranks grid mutability on confirm; non-`TENTATIVE` or a `CANCELLED` show is `ERR_INVALID_STATE` — `routes/schedule.py:232-239`
- §3.4 — revise — ambiguity — the idle fallback ignores `SUPERSEDED` grids, applies from any live status, is skipped for `APPROVED_UNSCHEDULED`/`CANCELLED`; non-live release is `ERR_INVALID_STATE` — `services/domain.py` `revert_to_unscheduled_if_idle`, `routes/schedule.py:258`
- §3.4 — insert — ambiguity — reinstatement changes nothing on the show; non-`PREEMPTED` is `ERR_INVALID_STATE` — `routes/schedule.py:266-287`
- §3.5 — revise — ambiguity — all four creation fields are required and all three identifiers resolve before the structural binding — `routes/episodes.py:45-60`
- §3.5 — revise — ambiguity — `day_of_week` uses the grid's 0=Sunday convention; either mismatch is `ERR_EPISODE_SLOT_MISMATCH` — `routes/episodes.py:62-70`
- §3.5 — insert — mismatch — `substitute_board_operator_volunteer_id` is mandatory only for `SUBSTITUTE_AIRED` (`ERR_VALIDATION`), and `ERR_PROGRAM_RESTRICTED` guards all three outcomes including `MISSED` — `routes/episodes.py:117-124`
- §3.5 — revise — mismatch — the operator test on `AIRED` and on the substitute both include roster status (not `SUSPENDED`/`RESIGNED`) — `services/domain.py` `operator_is_live`
- §3.5 — revise — ambiguity — `MISSED` applies no certification test at all — `routes/episodes.py:138-146`
- §3.5 — revise — ambiguity — `sequence_number` has no upper bound and need not be contiguous or filed in order — `routes/episodes.py:160-175`
- §3.5 — revise — ambiguity — a null-operator airing still refuses with `ERR_NOT_BOARD_OPERATOR`; airings browsable by `program_id`…`needs_substitute` — `routes/episodes.py:82-87`
- §3.5 — revise — ambiguity — `review_note` is accepted and discarded; a non-`SUBMITTED` log is `ERR_INVALID_STATE`; `CERTIFY` leaves `provisional_royalty_cents`; `RETURN` clears only that one field — `routes/episodes.py:238,247`
- §3.5 — insert — ambiguity — an empty featured set yields integer `0`, not null, in both variants — `services/calc.py:245-258`
- §3.6 — insert — mismatch — `assigned_program_id` is required at submit-for-review, not at drafting; when supplied it must resolve — `routes/underwriting.py:44,131-132`
- §3.6 — insert — ambiguity — an amendment leaves omitted/null fields alone (no clearing), and a one-ended window change is checked against the stored other end — `routes/underwriting.py:101-118`
- §3.6 — revise — ambiguity — submit re-checks the stored flight window; a non-`DRAFT` spot is `ERR_INVALID_STATE` — `routes/underwriting.py:128-136`
- §3.6 — insert — mismatch — review is reachable only from `UNDER_REVIEW`, and the edited copy is screened *first*, so `ERR_EDITED_COPY_STILL_NONCOMPLIANT` outranks `ERR_POLITICAL_COPY_UNCENSORABLE` — `routes/underwriting.py:145-152`
- §3.6 — revise — ambiguity — plain `APPROVED` sets `approved_copy_text` to the `copy_text`; an edit against sub-25 copy is screened then discarded, landing `APPROVED` — `routes/underwriting.py:155-170`
- §3.6 — insert — ambiguity — an edit offered against ≥60 copy is screened then discarded and the spot is still `REJECTED` — `routes/underwriting.py:150-162`
- §3.6 — revise — mismatch — the public-file obligation attaches on `APPROVED_WITH_EDITS` as well as `APPROVED` — `routes/underwriting.py:27,176`
- §3.6 — insert — ambiguity — a posting at or after `public_file_due_at` lands `LATE_POSTED`; `public_file_reference` is required non-empty — `routes/underwriting.py:190-196`
- §3.6 — insert — ambiguity — the sweep-raised incident's full field set (null respondent/episode/adjudicator/remediation, `sanction` `NONE`, `safe_harbor_violation` false, exact `complainant_note`, null `program_id` tolerated) — `services/domain.py` `daily_sweep`, `services/records.py:1-37`
- §3.7 — revise — ambiguity — all four pointers resolve before any target check, so a bad respondent is `ERR_VOLUNTEER_NOT_FOUND` — `routes/underwriting.py:225-245`
- §3.7 — revise — ambiguity — incidents browsable by `severity` — `routes/underwriting.py:259`
- §3.7 — insert — ambiguity — segregation-of-duties passes freely when `reviewed_by_user_id` is null or no spot is named — `routes/underwriting.py:311`
- §3.7 — revise — ambiguity — remediation un-suspends only a still-`SUSPENDED` respondent and reverses no other sanction — `services/domain.py` `remediate`
- §3.8 — insert — ambiguity — score, method and `last_evaluated_at` are written on every accepted review, and the host's `seniority_score` is recomputed in the same request — `routes/programs.py:79-87`
- §3.8 — insert — ambiguity — equal `scheduled_start_utc` in `TRAILING_SIX` is broken by write order, later wins — `services/calc.py:366`
- §3.8 — revise — ambiguity — the sweep recomputes each show and demotes only below `60.00`; a demoted show still appears in `reviewed_program_ids` — `services/domain.py` `daily_sweep` phase 4
- §3.9 — insert — ambiguity — activation only from `PLANNED`, closure only from `ACTIVE`, with the state check ahead of `ERR_PLEDGES_PENDING` — `routes/development.py:132-152`
- §3.9 — insert — ambiguity — the volunteer-calendar conflict spans every drive, not just the one being staffed — `routes/development.py` `_volunteer_shift_conflict`
- §3.9 — revise — ambiguity — only a `SCHEDULED` shift closes; `COMPLETED` counts pledges regardless of later settlement; `NO_SHOW` leaves `pledges_taken_count` — `routes/development.py:185-205`
- §3.9 — revise — ambiguity — `received_qty` ≥ 1; premium tier/FMV/name fixed at registration; premiums browsable by derived `status` and by `sku` — `routes/development.py:237-262`
- §3.9 — insert — ambiguity — `WAIVE` needs only the `RESERVED` earmark and only `SHIP` is gated on `PAID`; both answer `ERR_PREMIUM_NOT_RESERVED` first — `routes/development.py` premium-fulfillment
- §3.9 — insert — ambiguity — refund leaves any non-`SHIPPED`/`RESERVED` `premium_status` untouched; refund only from `PAID`, settlement only from `PENDING` — `routes/development.py` refund
- §4 — revise — ambiguity — episodes row now lists `needs_substitute` — `routes/episodes.py:87`
- §4 — revise — ambiguity — incidents row now lists `severity` — `routes/underwriting.py:259`
- §4 — revise — ambiguity — premiums row now lists `sku` and notes `status` filters on the derived value — `routes/development.py:237-238`

Key findings worth flagging: the seven highest-risk divergences were the §3.3 ballot ordering (self-vote outranks not-in-review), the case-insensitive language bonus, `ERR_PROGRAM_RESTRICTED` guarding `MISSED`, the substitute operator's roster-status requirement, `assigned_program_id` enforced at submit rather than draft, the public-file obligation attaching on `APPROVED_WITH_EDITS`, and `needs_core_renewal` being status-derived (so it stays false past an expiry until the sweep runs).

**Orchestrator verification:** `PRD_COMPLETED.md` present at 568 lines / 139,345 bytes, tail ends on the complete final error-catalogue row — no truncation. Pipeline complete.
