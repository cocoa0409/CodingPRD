# Worklog — task_2628_resort_fee_ancillary_charge_disclosure_compliance

## Step 1: Create task directory — 2026-09-03T21:45:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2628_resort_fee_ancillary_charge_disclosure_compliance` and its `workspace/` subdirectory. Index 2628 was pre-assigned by the orchestrating prompt; no scan of `./tasks/` was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-03T23:40:00.000Z

All three scaffold artifacts are complete and lint-clean.

## Files written
`/home/ubuntu/github/CodingPRD/tasks/task_2628_resort_fee_ancillary_charge_disclosure_compliance/`

| File | Lines | Contents |
|---|---|---|
| `SCAFFOLD.yaml` | **3862** | §1.0–§1.7 only (verified: no `scaffold_difficulty_design` / `scaffold_corner_design` keys). 15 entities, 7 state machines + 2 `concurrency_rules`, 16 calculations, 44 priority-ordered validations, 72 endpoints, 60 error codes, 7 roles (`role_model: segregation_of_duties`, `entity_topology: graph`, `state_machine_shape: cyclic`, `difficulty_level: expert_plus`). |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | **3096** | Single top-level key. 9 `rule_id` blocks / **22 instances** (3,3,3,2,2,3,2,2,2). |
| `SCAFFOLD_CORNER_DESIGN.yaml` | **5793** | Single top-level key. **85 instances** across all nine claim-extraction-guide sections — entities 12, state_machines 15, calculations 11, validations 23, endpoints 7, errors 6, rbac 4, cross_cutting_complexity_layers 6, consistency_model 1 — of which 64 are full recipes and 21 are `excluded_because` stubs. |

## Lint verdict (verbatim)
```
Coverage
  §1.5 endpoints declared:    72
  §1.1 entities declared:     15
  §1.8 instances scanned:     22
  §1.9 instances scanned:     64
  Calls scanned (§1.8+§1.9):  1462

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Verification beyond the linter
- Every one of the 60 error codes is now triggered by at least one instance (a script comparing the §1.6 catalog against both design files reports 0 uncovered; the last 15 — the six auth/SoD codes and nine 404s — were closed by the new `errors` and `rbac` sections).
- All 21 stub citations resolve to real §1.8 instance names; no stub carries a `test_recipe`; no full instance is missing one; all 107 names are globally unique; all `claim_type` values are rows of `references/claim-extraction-guide.md`.

## Scaffold defects found and repaired while writing §1.9
- `Property.open_disclosure_obligation_count` field description carried a 2-term formula while `property_disclosure_posture` and `disclosure_obligation_conservation` INVARIANT_1 use 4 terms — description rewritten to the 4-term form.
- `POST /bookings/{id}/guest-complaints` side effects claimed `refund_variant` / `disputed_amount_cents` / `disclosed_amount_cents` were captured at creation, contradicting the entity fields and `complaint_refund_entitlement` (both say substantiation) — endpoint now states they stay at their defaults until substantiation.
- Envelope drift: `response_type` is a top-level key with values `object|array|error`, so one assert reading `meta.response_type LIST` was corrected, and a `disputed_amount_cents null` assert was corrected to the declared default `0`.

The corner file ends at a real structural boundary (the final `assert:` line of `every_derived_field_is_visible_in_the_writing_response`). The hard constraint was honored throughout: no sibling `tasks/task_*/` directory was listed, read, or grepped — only the task's own directory, `/tmp` scratch, and the scaffold-generator skill's `SKILL.md`, `references/claim-extraction-guide.md` and `scaffold_lint.py`.

## Step 3: Copy shared files — 2026-09-03T23:41:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T00:01:00.000Z

PRD.md is complete at `/home/ubuntu/github/CodingPRD/tasks/task_2628_resort_fee_ancillary_charge_disclosure_compliance/workspace/PRD.md`.

**Build method:** 12 sequential `cat >> PRD.md <<'PRDEOF'` heredoc appends (no single large Write). Never opened `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`.

**Final state:** 521 lines / 124,631 bytes. Last section heading is `## 5. Error Code Catalogue`, and the file ends on a complete final table row (`| ERR_REFUND_EXCEEDS_ENTITLEMENT | 422 |`) — a real section boundary, no mid-sentence truncation.

**Structure:** §1 Introduction; §2 Global Specifications in 10 subsections (RBAC and the 7 roles incl. the 2 entity-backed ownership scopes and 3 duty separations; verbatim §2.2 envelope; pagination; logical clock; identity/version/immutability; nested path resolution plus the complete 1–44 validation precedence ladder; OCC; rounding discipline; cascade propagation; conservation invariants); §3 Business Logic in 9 subsections (jurisdictions/taxability/property estate; fee-program authoring and publication; disclosure profiles, scoring, deployment, remediation; quoting and the two booking status dimensions; folio itemisation and variance reconciliation; opt-outs; complaints; regulator dockets; revenue-impact modelling); §4 the 4-column endpoint table; §5 the 2-column error table.

**Hard Contracts — all PASS (verified programmatically):**
- **Contract 1 (Field-Name Coverage):** 164 scaffold field / request-body / query-param / path-param names extracted; all present verbatim in backticks. The only unmatched tokens are 16 internal calculation identifiers plus the two variant labels `per_night_rounding` / `stay_aggregation`, which are scaffold-internal names, not API surface — both rounding orders are documented in prose. Also verified: all 60 error IDs appear in §1–§4 prose (none catalogue-only), all enum literals from every `one of {...}` constraint appear, all 7 role names appear.
- **Contract 2 (Rule Coverage):** all 7 state machines / 46 transitions, all 16 calculations with their pinned step orders and worked reference integers (17552 vs 17550, tax 18003 vs 18002, variance −3, gap 5572, refunds 2600 and 3367, exposure 5572/0, commission boundary 32854→6300 vs 32855→7350, scores 100/60/55/0), all 44 validations with priorities and error IDs, both OCC rules, all cross-entity cascades (4-link supersession, 4-link substantiation, 4-link require-remediation, withdrawal compensation), sibling-branch symmetry (substantiate vs dismiss; grant vs revoke; RATE_PARITY vs TAX_ABSORBED), all field-level defaults, and all endpoint side effects.
- **Contract 3 (§3 Path Purity):** 0 violations — no backtick token in §3 starts with `/`, is a bare HTTP method, or combines method+path. Paths appear only in §2.7, §2.6 and the §4 table.

**Scaffold conflicts resolved (kept consistent throughout):** pagination from `response_envelope.pagination_defaults` (10/1/100/0) over the endpoints-header comment; refund variant mapping from the `calculations` block (`MISSTATED_AMOUNT` → `DISCLOSURE_GAP_DIFFERENTIAL`, the other three → `FULL_FEE_REFUND`) over the contradictory field description; `WITHDRAWN` reachable from 4 states per the state machine's explicit note (not `REMEDIATION_SUBMITTED`); `ACCEPTED` documented from `REMEDIATION_SUBMITTED` and, per the endpoint note, from `RESPONSE_SUBMITTED` when no remediation was ordered; folio total subtracts `credits_total_cents` per the calculation and the field's own clarifying note; unmapped preconditions given definite codes (`ERR_INVALID_STATE` for close-blocked-by-complaint and re-post-blocked-by-live-opt-out, `ERR_INVALID_REQUEST` for cross-field consistency mismatches). One late fix: `ERR_RESPONSE_WINDOW_EXPIRED` corrected to HTTP 409 to match both the validations table and the error catalogue.

**Orchestrator truncation verification (independent of subagent report):** `wc -l` = 521; §4 endpoint table has exactly 72 method rows matching the scaffold's 72 endpoints; §5 has exactly 60 `ERR_` rows matching the scaffold's 60 error ids; `tail` confirms the file ends on a complete table row inside §5. Not truncated — no regeneration needed.

## Step 6: Generate implementation — 2026-09-04T01:15:00.000Z

(Steps 5 and 6 were launched concurrently in a single assistant message, per the skill; Step 6 returned first, so its entry is recorded first. Step 5's entry follows below.)

Implementation complete and verified.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2628_resort_fee_ancillary_charge_disclosure_compliance/workspace/implementation/` — 19 files, 3747 lines, Python 3 + Flask, in-memory dicts only:

| file | lines | role |
|---|---|---|
| `start.sh` | 10 | guarded `pip install`, `exec python3 app.py` (executable) |
| `requirements.txt` | 1 | `Flask==3.0.3` |
| `app.py` | 77 | blueprint registration, `ApiError`/404/405/400/HTTPException/500 envelope handlers, `0.0.0.0:$PORT` (default 10000) |
| `errors.py` | 84 | all 60 error ids → HTTP status |
| `clock.py` | 66 | logical clock, startup `2026-08-01T00:00:00Z`, 3-fractional-digit ISO |
| `store.py` | 135 | 15 dicts, id/version/timestamp stamping, lookups |
| `envelope.py` | 138 | `meta`/`response_type`/`data`, `req_`+20 chars, paging 10/1/100, filters |
| `serialize.py` | 209 | 15 serializers (FolioLine + RevenueImpactModel leaner: id + created_at only) |
| `auth.py` | 97 | `X-User-ID`/`X-User-Role`, 7 roles, ladder ranks 1-5 |
| `shape.py` | 157 | rank-7 field shape validators |
| `calc.py` | 320 | 16 calculations on `fractions.Fraction`, `round_half_up`, no floats |
| `derive.py` | 191 | folio aggregation, scoring, property recomputation, cascades |
| `resolve.py` | 92 | 14 not-found resolvers + non-raising `peek` |
| `routes_config.py` | 258 | clock, jurisdictions, taxability rules, properties, channels |
| `routes_fees.py` | 371 | fee programs, fees, inclusions, submit-review, publish + supersession |
| `routes_profiles.py` | 273 | disclosure profiles, deploy/audit/remediate/confirm-remediation |
| `routes_bookings.py` | 398 | bookings, stay progression, folios, itemize/post/close, folio lines |
| `routes_guest.py` | 470 | opt-out requests (grant/deny/revoke), complaints (investigate/substantiate/dismiss/refund) |
| `routes_regulator.py` | 400 | regulator inquiries (8 transitions), revenue-impact models |

Route map diffed programmatically against the scaffold's endpoint table: **exactly 72 endpoints, zero missing, zero extra.**

## Smoke test (port 18628, PID killed individually; no broad pkill used)

An end-to-end script drove the full canonical PRD fixture and **every worked number matched (0 failures)**: quote 119600/17552/18003/155155 and gap 5572; folio lines 119600/16002, 8970/1200, 5980/800, 2600/0 with the four distinct taxability determinations; folio total 155152, variance −3, no dispute at |−3| ≤ 100; opt-out credit 5980/800 dropping out-of-pocket to 148372 and revoke restoring exactly 155152; entitlements 2600 (FULL_FEE_REFUND) and 3367 (DISCLOSURE_GAP_DIFFERENTIAL, *not* 3368); revenue model deltas −226 (RATE_PARITY) and −3610 (TAX_ABSORBED) with ADRs 32045/28263; docket cascade flagging → posture NON_COMPLIANT, min score 0, quote swept to DISPUTED, exposure 5572 in-scope / 0 for GDS, `ERR_REMEDIATION_INCOMPLETE`, withdrawal restoring DEPLOYED with no drift. Also confirmed 403 `ERR_SEGREGATION_OF_DUTIES` on publish and submit-response, `ERR_BOOKING_OWNERSHIP_REQUIRED`, `ERR_DUPLICATE_DOCKET_NUMBER`, `ERR_INQUIRY_SCOPE_EMPTY`, unmatched filter → empty array (not an error), and `limit=0` → `ERR_INVALID_REQUEST`.

## Notes for the caller

- Store starts empty on every boot; nothing seeded, no SQLite/disk/`/tmp` persistence. `__pycache__` removed.
- `test_suite/` and `test_helpers/` were never read or written; the implementation derives from `PRD.md` alone.
- PRD-over-scaffold decisions worth knowing: withdrawal is **not** reachable from `REMEDIATION_SUBMITTED` (scaffold said it was); reject-remediation re-flags exactly the ids already in `flagged_profile_ids` (not "every in-scope DEPLOYED profile"); `channel_scope` duplicates are rank-7 `ERR_INVALID_REQUEST` while empty/non-member is rank-35 `ERR_INQUIRY_SCOPE_EMPTY`; pagination is 10/1/100; refund variant is `FULL_FEE_REFUND` for all reasons except `MISSTATED_AMOUNT`.
- Two judgement calls a test could disagree with: `COMPLAINT_REFUND` lines carry the disputed line's `fee_id`/`fee_code` (the PRD only says fee_id is null on refunds "that are not fee-specific"); and for ownership ranks 4/5, a nonexistent resource falls through to the rank-6 404 while an unknown `X-User-ID` always yields 403.

## Step 5: Generate unit tests — 2026-09-04T02:50:00.000Z

All repairs are applied and the suite is green on every check.

## What was done in this final pass

**10 docstring citation repairs** (docstrings only — no assertion logic touched), each replacing a paraphrase with the PRD's byte-verbatim sentence:

| File | Repair |
|---|---|
| `test_04_fee_program_and_profile_validations.py` | ladder ranks 33/34 now quote `"33. Roll-in code that is not a mandatory fee — \`ERR_ROLL_IN_FEE_NOT_MANDATORY\`."` / `"34. Roll-in set inconsistent with the declared scenario — …"` |
| `test_06_endpoint_contracts.py` | real §3.3 **Auditing** sentence ("A `ComplianceOfficer` may audit a profile at any time…strictly below 60…") |
| `test_08_role_based_access.py` | real §3.4 booking-payload sentence ("the `channel_id` supplied must be the profile's own channel…`ERR_INVALID_REQUEST`") |
| `test_10_quote_and_folio_rounding_divergence.py` | ASCII `-3` → PRD's U+2212 `−3` |
| `test_14_profile_and_booking_state_machines.py` | invented `"taken from \`REMEDIATED\`"` → §3.3's "Confirmation is a `ComplianceOfficer` action and moves a profile `REMEDIATED → DEPLOYED`, closing the cycle …" |
| `test_15_disclosure_cascades.py` (2 tests) | "Link one…five" invention → §3.7's real four-level cascade text, and for the sibling-sweep test the Level-four continuation plus §3.4's "A booking in `PENDING_AUDIT` whose `stay_status` is still `QUOTED` transitions to `DISPUTED` when its property's `disclosure_posture` becomes `NON_COMPLIANT`…" |
| `test_16_validation_precedence_conflicts.py` (2 tests) | `described in 2.7` → `described in §2.7`; `mandatory_fee_ban` paraphrase → §3.1's real sentence |
| `test_17_cross_entity_state_dependencies.py` | §3.3 remediation-success sentence verbatim, including the "sins of the path it replaced" clause and `last_audited_at` |

Note the §3.4 check confirmed the disputed-sibling assertions in `test_15` were sound all along — only the citation was fabricated; the PRD does derive that edge (posture → `NON_COMPLIANT` sweeps `QUOTED`/`PENDING_AUDIT` bookings).

Also removed 3 genuinely unused imports (`typing.Any` in `test_helpers/types.py`; `BASE_ROOM_RATE_CENTS` and `create_fee_inclusion_payload` in `test_helpers/fixtures.py`) and verified both names still resolve through `test_helpers` for the tests that import them.

## Verification (all green)

- **Citation audit:** 227 quoted fragments, **0 non-verbatim** against `workspace/PRD.md`.
- **Static:** `ast.parse` OK on all 20 files; `PYTHONPATH=. importlib` imports all 19 test modules; `pyflakes` exit 0 on `test_suite/*.py` and on the two edited helpers (remaining warnings are only the intentional façade re-exports in `test_helpers/__init__.py`).
- **Design-tag audit:** 110 test functions, 110 tagged, exactly one `Design:` line each and always the docstring's last line; **0 stray tags**, **0 excluded-but-tested** (all 21 `excluded_because` corner instances untouched), **64/64 live corner instances covered**, **22/22 difficulty instances with ≥2 tests**.
- **Forbidden tokens:** no `scaffold`, no `pytest.mark.skip/xfail/skipif` anywhere in either directory.
- **Paths:** `test_helpers/` and `test_suite/` are at the task root; `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation` — no stray copies. Nothing under `workspace/implementation/` was read or written.

## Final inventory

`test_helpers/` — 2525 lines
```
  47 __init__.py     325 api_client.py    150 api_errors.py   422 assertions.py
 103 constants.py    208 factories.py     695 fixtures.py      95 test_users.py
 480 types.py
```

`test_suite/` — 7222 lines, 110 tests
```
  65 conftest.py                                620 test_01_reference_data_entities.py
 707 test_02_lifecycle_state_machines.py        241 test_03_disclosure_calculations.py
 760 test_04_fee_program_and_profile_validations.py  761 test_05_folio_and_guest_validations.py
 375 test_06_endpoint_contracts.py              447 test_07_error_catalogue.py
 414 test_08_role_based_access.py               176 test_09_concurrency_and_consistency.py
 241 test_10_quote_and_folio_rounding_divergence.py  191 test_11_revenue_roll_in_modelling.py
 216 test_12_complaint_refund_variants.py       299 test_13_disclosure_score_composition.py
 360 test_14_profile_and_booking_state_machines.py   280 test_15_disclosure_cascades.py
 221 test_16_validation_precedence_conflicts.py 219 test_17_cross_entity_state_dependencies.py
 268 test_18_temporal_overlap_and_cutover.py    361 test_19_compensating_invariants.py
```

Generation is complete. The suite has not been executed against an implementation (per the isolation constraint), so the next step for the caller is the Step 7 sweep once the implementation generator finishes.

**Orchestrator layout verification:** `test_helpers/` and `test_suite/` confirmed at the task root; `workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `implementation/`. 20 files in `test_suite/`, 110 `def test_` functions. `__pycache__` directories removed before the Step 7 sweep.

## Step 7: Run tests and iterate — 2026-09-04T03:35:00.000Z

Clean 8-round sweep achieved: **110/110 in all 8 parallel rounds**.

## Summary

**Iterations run:** 2 (first sweep: 96–97/110 with 13 hard failures + 1 flaky; second sweep: 8×110/110).

**Tests deleted:** none wholesale. Four individual assertions were removed under the PRD-silence / non-derivability rules (STEP 1a/1b with 1c partial-coverage handling):

- `test_02…::test_check_in_before_the_arrival_instant_leaves_no_orphan_folio` and `…::test_closing_the_folio_expires_an_undecided_opt_out_without_moving_money` — both asserted a folio `closed_at` field. **PRD silence:** §3.5 enumerates the folio's fields (`booking_id`, `status`, `line_count`, the four money aggregates, `itemization_complete`, `posted_at`) and never names `closed_at`.
- `test_02…::test_paying_a_substantiated_complaint_appends_a_credit_and_cures_the_stay` — asserted `COMPLAINT_REFUND.fee_id is None`. **Unique-derivability collapse:** §3.5 says `fee_id` is null "on complaint refunds that are *not* fee-specific" while §3.7's refund paragraph never states which a complaint refund is; since a complaint always names a `folio_line_id` carrying a fee, both "null" and "the disputed line's fee" are PRD-faithful readings. (This was the implementation generator's flagged judgement call — resolved in the implementation's favour by deleting the non-derivable assertion.)
- `test_04…::test_a_fee_code_is_unique_only_inside_its_own_inventory` — asserted `fee_count == 0` on a DRAFT program that already holds a fee. **Unique-derivability collapse, and the suite contradicted itself:** `test_08…` line 177 asserts `fee_count == 1` in the identical situation. §3.2 names submit-review as the refresh point while §2.9/§2.5 describe parent counters as live denormalisations, so either reading is faithful.

**Fixes applied to `test_helpers/`:**
- `assertions.py` → `assert_folio_ledger_conservation`: the `taxes` term re-signed credit-line taxes (`-line["tax_cents"]`), double-negating an already-negative stored value. PRD §3.5: "`tax_total_cents` is the sum of `tax_cents` over **every** line, credits contributing their negative values" — now a plain sum. This one fixture bug caused both `test_19` failures.

**Fixes applied to `test_suite/` (STEP 2, test made more faithful to PRD):**
- `test_01…::test_the_program_list_filters_by_status_before_it_pages` — the source of the flakiness. Both programs are created at the same frozen logical clock, so §2.3's declared tiebreaker (`id` ascending) decides page order, not insertion order; expectations now derive from `sorted(..., key=id)`.
- `test_02…::test_a_repeated_action_call_is_a_conflict_and_not_a_second_success` — the test builds two full configurations, and the second reused jurisdiction `code` `US-NV-CLARK`, which §3.1 declares globally unique; the second env now registers `US-NV-WASHOE`.
- `test_02…::test_dismissal_clears_the_booking_and_touches_nothing_else` — `refunded_amount_cents is None` → `== 0` (§3.7: "a system `refunded_amount_cents` defaulting to 0").
- `test_02…::test_an_adjusted_folio_must_be_reposted_before_it_can_ever_be_closed` — the test revoked the opt-out *after* re-posting, but §3.6 requires the folio to be in `ADJUSTED` for revocation. Reordered so the mirror rebill lands while `ADJUSTED` (also now asserting §3.5's "a folio already in `ADJUSTED` stays there when a further compensating line lands" and the second refusal of the close edge), with the post-rebill aggregates asserted at the repost.
- `test_06…` `SUMMARY_FIELDS` — dropped `total_mandatory_fee_cents_per_night`; §3.1 lists the Property row's computed fields and that burden figure is summary-only (the suite's own `assert_disclosure_summary_matches_property` helper already excluded it). The summary's own `== 4388` assertion is retained.
- `test_06…::test_an_audit_always_stamps_the_clock_and_flags_only_under_sixty` — `last_audited_at is None` after deployment contradicted §3.3 ("On success the profile's `disclosure_score` is recomputed and its `last_audited_at` is stamped with the current logical clock"); now asserts the stamp.
- `test_08…::test_one_channel_may_not_quote_a_stay_on_another_channels_path` — when the rival names its *own* `channel_id`, the new booking's `channel_id` equals `X-User-ID`, so rank 4 ownership passes and §2.6 rank 7 answers with `ERR_INVALID_REQUEST`/422 per §3.4's mismatch rule; assertion corrected from `ERR_CHANNEL_OWNERSHIP_REQUIRED`.
- `test_18…::_profile_attempt` — used `ComplianceOfficer` to `POST /channel-disclosure-profiles`, which §4 authorises for `RevenueManager`/`ChannelOperator` only, so the intended `ERR_CUTOVER_BUFFER_VIOLATION` was pre-empted by `ERR_FORBIDDEN_ROLE`; now issued by `REVENUE`.

**Fixes applied to `implementation/`:** none. Every failure traced to the test artifact; the second judgement call flagged by the implementation generator (rank 4/5 fall-through to the rank-6 404 for a nonexistent resource, 403 for an unknown `X-User-ID`) was never contradicted by any test.

**Orchestrator independent verification of the final sweep artifacts:** all 8 `results.$i.json` exist and parse; each reports `passed 110 / failed 0 / errors 0 / skipped 0 / total 110`, ~200s per round. `find` confirms no `.py` under `test_suite/`, `test_helpers/` or `implementation/` was modified after the sweep began, so the green result reflects the final source state. `grep` for `mark.skip` / `mark.xfail` / `skipif` across both test directories returns 0 hits — the pass was not bought with skips.

Step 8 is NOT skipped: Step 7 ran 2 iterations with 4 assertion deletions and 9 test-artifact fixes.

## Step 8: Finalize PRD — 2026-09-04T03:50:00.000Z

Done. Six targeted edits to `PRD_FINALIZED.md`.

**Line counts:** PRD.md 521 lines / 124,631 bytes → PRD_FINALIZED.md 521 lines / 126,121 bytes (0.0% line delta, +1.20% bytes; all six edits are in-line revisions, no new lines/sections).

**Changes**

- §3.1 (property computed fields) — revise — "Six further fields on a property are computed" → "Five ... and they are the whole of the property row's denormalisation" (the sentence's own list names five; impl stores exactly five) — `implementation/routes_config.py:163-167`, `implementation/serialize.py:29-34`, `implementation/derive.py:139-168`.
- §3.1 (disclosure summary) — revise — the blanket "Every field it reports must equal the denormalised counterpart stored on the property row" is scoped to the five fields that actually have a stored counterpart; `deployed_profile_count`, `flagged_profile_count` and `total_mandatory_fee_cents_per_night` are called out as summary-only derivations, the burden figure summed from the `PUBLISHED` programs' rollups — `implementation/routes_config.py:192-217`.
- §3.2 (appending a fee) — insert — appending a fee immediately refreshes the program's `fee_count` and `mandatory_fee_count` and counts as a mutation of the program per §2.5, so both are live denormalisations on a `DRAFT` program rather than review-time snapshots — `implementation/routes_fees.py:24-27,173-174`.
- §3.4 (booking create) — insert — a `ChannelOperator`'s rank-4 ownership check reads the payload `channel_id`, not the profile's, so naming your own channel on a rival's path clears rank 4 and falls to the rank-7 `ERR_INVALID_REQUEST` mismatch — `implementation/routes_bookings.py:44-45,61-63`, `implementation/auth.py:67-74`.
- §3.5 (folio-line `fee_id`) — revise — "null on `ROOM` lines and on complaint refunds that are not fee-specific" → null only on `ROOM` lines, otherwise carried over from the source line, so `FEE_CREDIT`, `FEE_REBILL` and `COMPLAINT_REFUND` repeat the compensated line's `fee_id` — `implementation/derive.py:24-42`, `implementation/routes_bookings.py:264,280-284`, `implementation/routes_guest.py:166-171,226-231,453-457`.
- §3.7 (refund) — insert — the `COMPLAINT_REFUND` line is fee-specific: `fee_id` and `fee_code` copied from the disputed line — `implementation/routes_guest.py:452-457`.

**Per-edit pre-edit search log**

1. *Property computed-field count.* (a) Subject: which computed fields live on the Property row. (b) Enumerated: `routes_config.py` create_property row literal (5 computed fields), `serialize.PROPERTY_FIELDS`, `derive.recompute_property` (writes exactly those 5), `derive.min_channel_disclosure_score/published_fee_program_count/open_disclosure_obligation_count/aggregate_disclosure_gap_cents`; grepped `total_mandatory_fee_cents_per_night` across all routes (only fee-program rows + the summary). (c) Added "and they are the whole of the property row's denormalisation" instead of naming a closed list twice, since the next sentence already enumerates them.
2. *Summary/row identity.* (a) Subject: the disclosure-summary payload vs stored property fields. (b) Enumerated: the summary handler `routes_config.py:192-217` field-by-field, `serialize.PROPERTY_FIELDS`, `derive.*` recompute helpers, and the fee-program rollup source of the burden figure (`routes_fees.py:353`, `calc.total_mandatory_fee_cents_per_night`). (c) Widened from "must equal the stored counterpart" to a named five-field identity plus an explicit summary-only trio, so the sentence no longer asserts stored counterparts that do not exist; kept the §2.10 rationale verbatim.
3. *fee_count / mandatory_fee_count.* (a) Subject: every writer of those two counters. (b) Enumerated all `_refresh_fee_counts` callsites — create_fee (173), submit-review (265), publish (352) — plus the create-program defaults (78-79) and `store.touch`/`§2.5`; confirmed no delete-fee route exists. (c) Phrased as "refreshes ... from the program's current fee rows" so the existing submit-review and publish refresh sentences stay true and idempotent; scoped to `DRAFT` because impl rejects fees on non-DRAFT programs (147-148).
4. *ChannelOperator rank-4 on booking create.* (a) Subject: what the rank-4 ownership comparison reads on each of the six guarded operations. (b) Enumerated every `channel_owns`/`acting_channel` callsite: `routes_bookings.py:45` (payload) and `:110-112` (stored booking), `routes_profiles.py:67` (payload), `:130-133`, `:155-158`, `:218-221` (stored profile), plus `auth.channel_owns`; confirmed `confirm` has no ownership check, matching §2.1's "exactly six operations". (c) Scoped the sentence to "this payload" on booking creation so it cannot be read as a claim about deploy/remediate/read, which compare the stored row.
5. *Folio-line `fee_id`.* (a) Subject: `fee_id`/`fee_code` on every line type. (b) Enumerated all five `derive.append_line` callsites (ROOM, MANDATORY_FEE, FEE_CREDIT, FEE_REBILL, COMPLAINT_REFUND) and the `append_line` defaults; confirmed no path ever writes an `OPTIONAL_FEE` line, so `ROOM` is the only null-fee_id type. (c) Chose "carried over from the source line the new line answers" rather than "always non-null on non-ROOM lines", keeping the claim about provenance rather than nullability, and left the existing `fee_code` clause untouched since it remains true.
6. *Complaint-refund line identity.* (a) Subject: the `COMPLAINT_REFUND` line's fee attribution. (b) Enumerated `routes_guest.py:452-457` (refund), the complaint-creation line-type guard (line must be `MANDATORY_FEE`/`OPTIONAL_FEE`), `derive.append_line`, and the other credit writer at `:166-171` for consistency of the sign/tax convention. (c) Added the qualifier "which by the creation rule always names a fee-bearing line" so the claim is grounded in the already-stated creation constraint rather than asserted as an independent universal.

**Not patched (PRD already determined the behaviour; Step 7 items were fixture/test bugs):** folio `closed_at` (impl's folio serialiser has no such field and §3.5 already closes the field list), program-list `id` tiebreaker (`store.sort_default` = created_at, id), duplicate jurisdiction `code`, `refunded_amount_cents` default 0, the `ADJUSTED`-only revocation + no `ADJUSTED → CLOSED` edge, `last_audited_at` stamped on deploy/audit/remediate/confirm, the §4 role table for `POST /channel-disclosure-profiles`, and the `assertions.py` credit-tax double-negation.

## Step 9: Complete PRD — 2026-09-04T04:35:00.000Z

**Orchestrator decision (recorded per the AUTONOMY directive):** Step 9 was run as **three sequential file-partitioned passes** rather than one whole-implementation scan. Rationale: this PRD is 521 lines / ~126KB over a 19-file / 3747-line implementation, and a single-pass scan of that surface reliably degrades into a no-op (the tell being a `PRD_COMPLETED.md` byte-identical to its source). Partitioning by implementation file group keeps each pass's reading budget inside a range where it can actually walk every branch. Each pass was launched only after the previous one returned, so all three edited the same accumulating file in place; passes B and C were explicitly told the file already existed and forbidden from copying or overwriting it.

Partition:
- **Pass A** — `app.py`, `envelope.py`, `errors.py`, `clock.py`, `store.py`, `serialize.py`, `auth.py`, `shape.py`, `resolve.py`, `routes_config.py`
- **Pass B** — `calc.py`, `derive.py`, `routes_fees.py`, `routes_profiles.py`
- **Pass C** — `routes_bookings.py`, `routes_guest.py`, `routes_regulator.py`

### Pass A (infrastructure + §3.1 reference data)

Created `PRD_COMPLETED.md` from `PRD_FINALIZED.md`. **10 ambiguity-pins, 1 mismatch-revision** (11 edits, 8 hunks):
- §2.1 — revise — ambiguity — whitespace-only header counts as empty (`ERR_UNAUTHENTICATED`); role match exact and case-sensitive; `X-User-ID` compared by exact string equality — `auth.py:37-42`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from uppercase letters and digits — `envelope.py:11,21`
- §2.2 — revise — ambiguity — `api_request_timestamp` comes from real wall-clock time, not the logical clock — `envelope.py:27`, `clock.py:65`
- §2.2 — insert — ambiguity — the four transport-level ids outside the §5 catalogue (`ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INVALID_REQUEST` 422 for web-layer malformed so HTTP 400 never returned, `ERR_INTERNAL` 500); uncatalogued ids default to 422; trailing slashes not significant — `app.py:40-63`, `errors.py:80`
- §2.3 — revise — ambiguity — non-integer/empty `limit`/`offset` is `ERR_INVALID_REQUEST`; omitted takes default; offset past end yields empty `data` with `total_count` unchanged — `envelope.py:59-83,123-127`
- §2.3 — revise — ambiguity — filters are exact case-sensitive raw comparisons; booleans accept `true/false/1/0` case-insensitively, any other value is a no-match not an error; unknown params ignored; filter+order precede the window — `envelope.py:103-137`
- §2.4 — revise — ambiguity — `to_iso8601` required, 200 with single `current_utc`; parsing accepts `Z`/`z`/numeric offset and normalises to UTC, zoneless read as UTC, unparseable → `ERR_INVALID_REQUEST`; microsecond storage rendered to 3 digits; store starts empty, no reset route; `PUT/PATCH/DELETE` are `ERR_METHOD_NOT_ALLOWED` — `clock.py:7,42-62`, `routes_config.py:27-39`
- §2.5 — revise — ambiguity — `updated_at` equals `created_at` until first mutation; serialised key order `id`, `created_at`, `updated_at`, `version`, then entity fields; unset timestamps and unsupplied optionals render as JSON `null`; internal counter and input-only concurrency tokens never serialised — `store.py:49-57`, `serialize.py:6-19`
- §2.6 rank 7 — revise — **mismatch** — blanket "every basis-points field lies between 0 and 10000" narrowed: `occupancy_tax_rate_bps`/`tax_rate_bps` are 0–5000, `percent_bps` is 1–10000 — `routes_config.py:51,104-105`
- §2.6 rank 7 — insert — ambiguity — four uniform conventions: explicit `null` ≡ omitted (never a stored null); no type coercion; absent/empty/`null` body reads as `{}` while non-object body is `ERR_INVALID_REQUEST`; undeclared body fields ignored — `shape.py:17-30,37-42,72-100`
- §3.1 — revise ×4 — ambiguity — jurisdiction mandate booleans required with no default; `fee_code` has no character-class restriction and an explicit `tax_rate_bps` of `0` is a real zero-rate override distinct from null fallback; the disclosure summary has exactly nine keys in order, is unpaginated, carries no identity quartet and never writes on read; both channel capability booleans required, channel is pure reference data with no status/counter/transition — `routes_config.py:52-53,102-105,192-217,228-239`

Verified already-pinned: the full 60-id error→status map is byte-exact to §5; envelope shape and status codes; `has_more`; default `created_at`,`id` list order across all 12 list endpoints plus the folio-line departure; clock startup instant; ladder ranks 1–8 mechanics incl. 401-before-403 and ownership-before-path-existence; rank 4/5 unknown-acting-id → 403 not 404; opaque-role ids never compared to entities; UUID4 ids, `version` from 1 by +1; the two lean serialisers; all 15 serializers' field names present in PRD; every `routes_config.py` role list matching its §4 row.

### Pass B (16 calculations + §3.2/§3.3)

Diff vs `PRD_FINALIZED.md` grew **48 → 96 lines**; hunks 8 → 24; file still 522 lines. **11 ambiguity-pins, 5 mismatch-revisions**:
- §2.10 — revise — mismatch — obligation count counts live complaints on **any** of the property's bookings, not only `DISPUTED`/`UNDISCLOSED_CONFIRMED` ones — `derive.py:110-115`
- §2.10 — revise — mismatch — `confirmed_undisclosed_count` invariant scoped to substantiations since the path's last remediation (PRD's unqualified equality contradicted §3.3's reset-to-0) — `routes_profiles.py:244`
- §3.2 — insert — ambiguity — duplicate `version_label` is `ERR_INVALID_REQUEST` and is the endpoint's last check, after the concurrency token and property-status tests — `routes_fees.py:62-65`
- §3.2 — revise — mismatch — fee list also filterable by `avoidable` — `routes_fees.py:192`
- §3.2 — insert — ambiguity — inclusions require a `DRAFT` program, tested before `service_code` uniqueness; recording one bumps no program `version` — `routes_fees.py:212-220,236`
- §3.2 — revise — mismatch — the `supersedes_program_id` triad sits at rank 14, right after the program's status test and before property status/posture/fee-ban/inclusion/taxability/overlap/effective-date, with its three error ids pinned — `routes_fees.py:291-300`
- §3.2 — insert — ambiguity — `attestation_note` required, unbounded, empty string accepted — `routes_fees.py:280`
- §3.2 — insert — ambiguity — `total_mandatory_fee_cents_per_night` is 0 for an all-optional program — `calc.py:81-88`
- §3.2 — revise — mismatch — publication also recomputes `open_disclosure_obligation_count` and `aggregate_disclosure_gap_cents`, and always bumps the property `version` even when `supersedes_program_id` is null — `routes_fees.py:369`
- §3.3 — insert — ambiguity — property status not tested at profile creation (a `DRAFT` path may be authored against a `SUSPENDED` property); creation fires no property recomputation — `routes_profiles.py:82-101`
- §3.3 — revise — mismatch — profile list also filterable by `disclosure_placement` — `routes_profiles.py:146`
- §3.3 — insert — ambiguity — audit legal only from `DRAFT`/`DEPLOYED`/`REMEDIATED`; `FLAGGED` and `RETIRED` are `ERR_INVALID_STATE` (PRD said "at any time") — `routes_profiles.py:198-200`
- §3.3 — insert — ambiguity — on a non-flagging audit the property `version` moves only when one of its five denormalised values actually changed — `routes_profiles.py:210`, `derive.py:166-167`
- §3.3 — insert — ambiguity — a rejected `confirm-remediation` persists nothing (score discarded, `last_audited_at` unchanged, no version bump) — `routes_profiles.py:263-266`
- §3.3 — insert — ambiguity — confirmation fires no retirement cascade, so two `DEPLOYED` paths can coexist on one property+channel — `routes_profiles.py:268-273`
- §3.4 — insert — ambiguity — the `NON_COMPLIANT` quote sweep fires only on the transition into `NON_COMPLIANT`, after min/posture but before the obligation count and aggregate gap — `derive.py:154-159`

Verified already-pinned: `rhu` half-up-away-from-zero, `bps_of`, all four `basis` expansions and their `Fraction` discipline, the `PER_STAY → amount/4` rule, inclusion coverage and its 0-mandatory convention, the full `disclosure_score` ladder (incl. `max` not `sum` of penalties and the single trailing clamp) with the 100/60/55/0 worked examples, `posture_for` boundaries, `aggregate_tax`'s one-rounding-per-rate ascending sum, the five-step quote order and 17552/134552/18003/155155, the positive-only gap and 5572/0, the stay-aggregation folio figures 8970/17550/18002/155152/−3, the three line determinations, the `commission_bps` tiers and 32854/32855 boundary, all baseline B1–B6 and modelled M1–M6 steps incl. the `TAX_ABSORBED` back-solve and all three delta sets (independently recomputed and matching), `refresh_folio`/`refresh_booking_money`, sequence contiguity, `effective_score`, the cutover-buffer comparison set, `create_fee` rank order, submit-review and publish rank chains, half-open overlap, `effective_from` inclusivity, the supersession fan-out, deploy's sibling retirement, remediate's guard-rail order and reset-then-rescore, the ≥80 confirmation floor.

### Pass C (bookings, guest, regulator)

Diff **96 → 168 lines**; hunks 24 → 42; file 522 lines; §5 still ends at `ERR_REFUND_EXCEEDS_ENTITLEMENT`. **16 ambiguity-pins, 3 mismatch-revisions**:
- §3.4 — revise — mismatch — the `channel_id`-vs-profile mismatch is not a rank-7 test: evaluated only after rank-8 resolution, so a nonexistent channel answers `ERR_CHANNEL_NOT_FOUND` in preference to `ERR_INVALID_REQUEST` — `routes_bookings.py:57-63`
- §3.4 — insert — ambiguity — check-in answers with the updated `Booking`, not the new folio; folio lands at `version` 1, `itemization_complete` false, `posted_at` null — `routes_bookings.py:172-187`
- §3.5 — insert — ambiguity — a `Guest` listing folio lines is row-scoped to its own booking's folios; a `folio_id` filter naming another booking's folio is `ERR_BOOKING_OWNERSHIP_REQUIRED`, one naming no folio yields an empty page — `routes_bookings.py:376-395`
- §3.5 — insert — ambiguity — the `ROOM` line's `description` is the literal `Room charge` — `routes_bookings.py:27,264-267`
- §3.5 — insert — ambiguity — itemisation recomputes the property's five values only when the tolerance gate disputes the booking, bumping `version` only where one moves — `routes_bookings.py:296-303`
- §3.6 — revise — ambiguity — a booking with no folio at all is rejected with `ERR_FOLIO_NOT_ADJUSTABLE` alongside `OPEN`/`ITEMIZED`/`CLOSED` — `routes_guest.py:31-36`
- §3.6 — insert — ambiguity — the `FEE_CREDIT` line's `description` is the fee's `disclosure_text`; `jurisdiction_id`/`fee_id`/`fee_code` copied from the source line — `routes_guest.py:166-171`
- §3.6 — revise — ambiguity — the `FEE_REBILL` line takes the original charged line's `tax_rate_bps` as well as its determination, and copies `description`/`jurisdiction_id`/`fee_id`/`fee_code` from the credit line — `routes_guest.py:221-231`
- §3.7 — insert — ambiguity — substantiation re-derives all five property values but bumps `version` only on flagging or an actual move — `routes_guest.py:394-396`
- §3.7 — insert — ambiguity — dismissal touches the property row only where a denormalised value moves (the obligation count always does) — `routes_guest.py:427-429`
- §3.7 — revise — ambiguity — the `COMPLAINT_REFUND` line carries `tax_rate_bps` 0, `description` `Complaint refund`, and the disputed line's `jurisdiction_id` — `routes_guest.py:28,453-457`
- §3.8 — insert — ambiguity — the five narrative fields are each required, unbounded strings (empty OK; missing/null/non-string is `ERR_INVALID_REQUEST`) — `routes_regulator.py:150,189,227,255,303`
- §3.8 — revise — mismatch — exposure is also recomputed when completed remediation is reported; drafting, acceptance and withdrawal leave it untouched — `routes_regulator.py:242` vs `159,291,318`
- §3.8 — insert — mismatch — the require-remediation sweep (link four) is unconditional, not gated on the descent into `NON_COMPLIANT`: it fires even when nothing was flagged or the property was already non-compliant — `routes_regulator.py:210-216`, `derive.py:130-136`
- §3.8 — insert — ambiguity — submit-remediation touches the property only where its recomputation moves a value — `routes_regulator.py:245-246`
- §3.8 — insert — ambiguity — rejection carries the §3.4 descent sweep through its forced recomputation, disputing `QUOTED`/`PENDING_AUDIT` bookings when the posture had recovered — `routes_regulator.py:272-273`, `derive.py:154-155`
- §3.9 — insert — ambiguity — all five model inputs required; `roll_in_fee_codes` has no default, so `STATUS_QUO` must send `[]` explicitly — `routes_regulator.py:335`
- §3.9 — revise — ambiguity — a repeated roll-in code is the rank-7 `ERR_INVALID_REQUEST`, not `ERR_ROLL_IN_FEE_NOT_MANDATORY` — `shape.py:126` via `routes_regulator.py:335`
- §3.9 — insert — ambiguity — a program with no `MANDATORY` fee admits `STATUS_QUO` and `FULL_ROLL_IN` with an empty array; `PARTIAL_ROLL_IN` is unreachable there — `routes_regulator.py:358-368`

Verified already-pinned: booking create's rank-8 order and `ERR_PROFILE_NOT_BOOKABLE`-before-`ERR_TAXABILITY_RULE_MISSING`; confirm's `QUOTED` gate and rank 14-before-15; check-in/out gates and departure arithmetic; itemise's per-line rounding, zero-amount skip and sequence numbering; post's two entry edges and undecided-opt-out block; close's `POSTED`-only gate, live-complaint block and opt-out expiry; folio-line ordering; opt-out create's four gates and inclusive window; grant's ladder, `TAXABLE_IF_MANDATORY_WAIVED` rule and byte-for-byte reversal; deny's rank-7 enum parse; revoke's `ADJUSTED`-only folio and counter reset; complaint create's rank-8 chain and default entitlement fields; investigate/substantiate/dismiss SoD-at-rank-9 and the conditional level-four flagging; refund's ladder and `CURED` source state; inquiry create's future `response_due_at` and duplicate-docket-before-empty-scope order; all 8 transitions' source-state sets incl. `WITHDRAWN` unreachable from `REMEDIATION_SUBMITTED`/`ACCEPTED`, flagging order by `created_at`, non-duplicating `flagged_profile_ids`, withdrawal restoring only still-`FLAGGED` ids, and exposure's scope+standing filter.

### Orchestrator final verification

- `PRD.md` 521 lines / 124,631 B → `PRD_FINALIZED.md` 521 lines / 126,121 B → `PRD_COMPLETED.md` 522 lines / 142,492 B.
- `cmp` confirms `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md`; 42 diff hunks, so all three passes' work is present and none overwrote another.
- `PRD_COMPLETED.md` structure intact: 5 `##` sections, §4 still holds exactly 72 endpoint rows, §5 exactly 60 `ERR_` rows, file ends at `ERR_REFUND_EXCEEDS_ENTITLEMENT` — no truncation.
- `find` confirms no `.py` under `implementation/` was modified after the green sweep began, so Steps 8 and 9 were documentation-only and the 8×110/110 result still describes the shipped implementation. The final `results.{1..8}.json` are retained in `workspace/implementation/`.

Pipeline complete.
