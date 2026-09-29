## Step 1: Create task directory — 2026-09-04T09:43:00.000Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2708_grassroots_advocacy_campaign_management and its workspace/ subdirectory. Index 2708 was pre-assigned by the orchestrating caller; no scan of ./tasks/ was performed (concurrent pipelines on this host).

## Scaffold generation complete (2026-09-04)
- SCAFFOLD.yaml: 13 entities, 70 endpoints (39 POST / 31 GET), 11 state-machine blocks over 9 entities,
  2 concurrency_rules, 13 calculations (2 with variants), 24 ordered validations, 50 error codes, 6 roles.
- SCAFFOLD_DIFFICULTY_DESIGN.yaml: 9 rule_ids x 2 = 18 instances.
- SCAFFOLD_CORNER_DESIGN.yaml: 86 instances across the 9 claim-extraction sections (70 with test_recipe,
  16 excluded_because stubs citing named §1.8 instances).
- scaffold_lint.py: VERDICT clean lint (979 calls scanned).

## Step 2: Generate scaffold (subagent) — 2026-09-04T11:52:00.000Z

Subagent summary (verbatim):

All three scaffold artifacts are complete and the linter is clean.

Files (all in tasks/task_2708_grassroots_advocacy_campaign_management/):
| File | Lines | Bytes |
| SCAFFOLD.yaml | 3,172 | 168,623 |
| SCAFFOLD_DIFFICULTY_DESIGN.yaml | 1,799 | 111,859 |
| SCAFFOLD_CORNER_DESIGN.yaml | 4,906 | 306,473 |

SCAFFOLD.yaml counts (§1.0–§1.7 only; no design keys present)
13 entities · 70 endpoints (39 POST / 31 GET; 69 under /advocacy + /_clock/set_current_utc) · 11 state-machine blocks over 9 entities (Campaign and Activation each carry two parallel dimensions) · 2 concurrency_rules (OCC) · 13 calculations (2 with divergent variants) · 24 ordered validations · 50 error codes · 6 roles · difficulty_level: expert_plus, role_model: segregation_of_duties, consistency_model: immediate.

Design indices
- SCAFFOLD_DIFFICULTY_DESIGN.yaml: single key scaffold_difficulty_design, 9 rule_ids × 2 = 18 instances (meets the >=2-per-rule / >=18 minimum).
- SCAFFOLD_CORNER_DESIGN.yaml: single key scaffold_corner_design, 86 instances — entities 12, state_machines 12, calculations 16, validations 27, endpoints 4, errors 2, rbac 5, cross-cutting complexity layers 7, consistency model 1. 70 carry a full test_recipe; 16 are excluded_because stubs, each citing a difficulty instance that exists by name. All 86 + 18 names are unique across the union; all 50 error codes are now referenced by at least one instance.

Lint verdict
  §1.5 endpoints declared:    70
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     70
  Calls scanned (§1.8+§1.9):  979
  VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.

§1.5/§1.2 fixes the §1.9 audit pass forced (all in SCAFFOLD.yaml)
- Added GET /advocacy/milestones (with campaign_id?) and GET /advocacy/consent-events/{consent_event_id} — the two FKs Milestone.campaign_id and ConsentEvent.supporter_id had no lint-recognised reverse-reachability read (endpoints 68 → 70; difficulty_level_note counts updated).
- Added the declared Campaign.posture RESTRICTED → OPEN edge for FORCE_OPEN (previously only FROZEN → OPEN existed, so the override-masks-a-blocked-wave corner had no grounding).
- Added MessageVariant LOCKED → RETIRED and removed the contradictory note: §1.5's message-test-resolution side effects said "losing variants in status APPROVED or LOCKED are RETIRED" while §1.2 claimed a LOCKED loser is never retired.
- Corrected the actor: on all five Activation delivery_state transitions (were MessageStrategist, contradicting §1.5/§1.7 roles: start-send/complete → CampaignDirector|FieldOrganizer, abort → CampaignDirector|ComplianceOfficer).
- Renamed one corner instance to unknown_body_fk_returns_404_before_a_malformed_body_returns_invalid_request so the intentional unknown payload key is recognised as a negative trigger, and replaced three list-envelope $.data.total_count captures (not addressable per the envelope) with prose asserts / an indexed $.data[0].channel capture.

No sibling task directory was read at any point.

ORCHESTRATOR NOTE: after the subagent exited, I stripped the line "Generate task harder than expert level!" from the `scenario:` block at the top of SCAFFOLD.yaml. That line is a difficulty instruction for the scaffold generator only; SCAFFOLD.yaml is the doc generator's input, so leaving it in place would have leaked a meta-instruction into PRD.md. No other scaffold content was touched.

## Step 3: Copy shared files — 2026-09-04T11:52:30.000Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD (subagent) — 2026-09-04T12:07:00.000Z

Subagent summary (verbatim):

All three Hard Contracts verified mechanically against SCAFFOLD.yaml. The PRD is complete and shipped.

Deliverable: workspace/PRD.md — 469 lines, ending at a clean section boundary (final line is the last row of the §5 error table, | `ERR_DELIVERY_TALLY_MISMATCH` | 409 |; no audit footer, no truncation).

Hard Contract reports

Contract 1 — Field-Name Coverage: PASS
- entities[].fields (+ computed-read output keys): 134 required / 134 present / 0 missing
- endpoints[].request_body: 65 / 65 / 0 missing
- endpoints[].query_params: 45 / 45 / 0 missing
- endpoints[].path_params: 13 / 13 / 0 missing
- Union: 161 names, 0 missing

Contract 2 — Rule Coverage: PASS
- validations priority ordering: all 24 priorities present in §2.8 as an explicitly numbered 1–24 ladder, each with its applies_to scope; all constituent error_ids (including the multi-error priorities 3, 4, 7, 13, 20, 22, 23, 24) resolve in prose
- concurrency_rules / OCC: both rules in §2.7 (expected_segment_version → ERR_STALE_SEGMENT_VERSION 412; expected_variant_version → ERR_STALE_VARIANT_VERSION 412, with endorsed_variant_version pinning)
- cross-entity side effects: 57 of 57 distinct field identifiers appearing in the 39 endpoints' side_effects are present in the PRD; the only unmatched tokens are the 13 internal calculation ids and 5 variant labels (campaign_posture, frequency_headroom, retention_score_final, …), which are scaffold-internal names deliberately not surfaced (their content is fully described in prose)
- field-level structured content: every enum value across all entity constraints present, 0 missing
- sibling-branch symmetry: activation_reach (projected vs realized) and supporter_value_score (engagement rolling vs retention final) each specified at equal density in separate subsections
- state machines: all 46 transitions across 11 blocks / 9 entities have their from and to states co-occurring in a single prose statement; all state values present
- calculations: all 13 documented; every numeric constant value present (thousand-separated forms, e.g. 10,000 for the basis-point scale, 999999 CPA sentinel, weights 5/3/1, 10.0 retention cohort floor); no symbolic constant names or pseudocode leaked

Contract 3 — §3 Path Purity: PASS
- 1163 backticked tokens scanned in §3: 0 starting with /, 0 bare HTTP methods, 0 method+path combinations. Paths appear only in §1, §2.7 and the §4 table.

Coverage counts: 70 endpoints (§4 table, exactly 4 columns, 70 rows, every method+path matched, 0 role omissions vs. endpoints[].roles) · 50 errors (§5, exactly 2 columns, 50 rows, 0 HTTP-status mismatches; all 50 also referenced in §2/§3 prose) · 13 calculations · 24 validations · 46 state transitions · 2 OCC rules · 6 roles.

Section list: Title; §1 Introduction; §2 Global Specifications (2.1 RBAC, 2.2 Response Structure [verbatim], 2.3 Pagination, 2.4 Identity/Timestamps/Versions, 2.5 Logical Legislative Clock, 2.6 Path Resolution, 2.7 Version Pinning, 2.8 Rejection Ladder, 2.9 Numeric Precision, 2.10 Derived Fields & Cascades, 2.11 Campaign Posture, 2.12 Consent & Frequency Governance); §3 Business Logic (3.1 Campaign founding & calendar, 3.2 Supporter list & consent replay, 3.3 Coalition funding & quorum, 3.4 Message testing lifecycle, 3.5 Segmentation & scheduling, 3.6 Delivery execution, 3.7 Constituent action & district matching, 3.8 Stories/spokespersons/meetings, 3.9 Close, retention scoring & outcome analysis); §4 Endpoint Definitions; §5 Error Code Catalogue.

Neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was opened, grepped or referenced, and no sibling task directory was read. One correction applied during generation: an invented consent_event_id → ERR_SUPPORTER_NOT_FOUND resolution rule in §2.6 was replaced with a neutral statement (the scaffold defines no ERR_CONSENT_EVENT_NOT_FOUND, so no resolution semantics were asserted).

ORCHESTRATOR VERIFICATION (truncation guard): wc -l = 469, 113,829 bytes. tail -25 ends on a complete markdown table row (ERR_DELIVERY_TALLY_MISMATCH | 409) which is the final §5 error row; grep of headings shows all of §1–§5 present with §5 starting at line 416. No mid-sentence or mid-table cut. PRD accepted without regeneration.

## Step 6: Generate implementation (subagent) — 2026-09-04T12:42:00.000Z

(Steps 5 and 6 were launched as concurrent subagents; Step 6 returned first. Its summary is recorded here, Step 5's below.)

Subagent summary (verbatim):

Implementation complete and verified. Server killed cleanly by recorded PID (1290985); port 18708 free.

Deliverable: workspace/implementation/

| file | lines | contents |
| calc.py | 891 | all constants + every derived calculation (pressure index, engagement/retention, quorum, cost share, variant metrics, segment membership, touch ledger, posture, outcome report, cascade driver) |
| common.py | 552 | envelope, 50-entry error catalogue, logical clock, in-memory DB, RBAC, shape validators, FK/path lookups |
| routes_story.py | 303 | spokespersons + district meetings (9) |
| routes_activation.py | 295 | activations (8) |
| serializers.py | 268 | per-entity output shaping |
| routes_campaign.py | 262 | clock + campaigns + nested reads (10) |
| routes_supporter.py | 243 | supporters + consent events (8) |
| routes_coalition.py | 235 | partners + endorsements (8) |
| routes_action.py | 215 | action records + thank-you loop (7) |
| routes_calendar.py | 213 | milestones + legislators (8) |
| routes_variant.py | 210 | message variants (7) |
| cascades.py | 207 | multi-hop system cascades (quorum demotion, revoke, retire, void, abort, close, complete) |
| gates.py | 173 | one helper per rejection-ladder rung |
| routes_segment.py | 133 | segments (4) |
| app.py | 86 | blueprint registration, ApiError/HTTPException/500 handlers, app.run(PORT or 10000) |
| start.sh (+x) | 10 | guarded pip install, exec python3 app.py |
| requirements.txt | 1 | flask>=3.0.0 |

4297 lines total. No seeded data: all 13 collections verified empty at boot, clock at 2026-08-01T00:00:00.000Z.

Verification
- 70/70 endpoints: a script-driven diff of Flask's url_map against the PRD §4 table is byte-identical on method+path, and a second pass compared each view's require_role(...) against the table's role column — zero mismatches.
- Smoke test (PORT=18708, ~55 assertions): full lifecycle through campaign → legislator → milestone → launch → 4 supporters → segment → variant submit/review-SoD/approve/lock → partner → endorsement → activation (cap 5 = 3+2 surge, projected 4) → stale-version 412 → clear → start-send → complete (PARTIAL, realized 3, cost 6c) → tally mismatch 409 → action (multiplier 2.0, pressure 22.00) → acknowledge → thank (eng 5.00 unchanged, ret 7.00, consumed 2) → dispute → filer-resolve 403 → reinstate → spokesperson TRAINED/CERTIFIED → meeting create/conflict-409/confirm/too-early-409/complete (pressure 38.00 SECONDARY) → outcome report (bps 5000, both reconciliation flags true) → close (FROZEN) → post-close write 409. Unknown path/405/malformed JSON/bad role all return the error envelope.
- Bug found and fixed during smoke: calc.actions_of_campaign read a non-existent denormalised _campaign_id; now derives campaign scope through the record's supporter.

PRD ambiguities resolved (named choices)
1. Ladder beats prose order. Where a §3.x "preconditions apply in order" list disagrees with §2.8's numbering, the numeric ladder wins (§2.8 is the declared tie-breaker). Concretely: rung 9 ERR_CAMPAIGN_FROZEN is raised before rung 11 ERR_INVALID_STATE_TRANSITION on the thank-you touch and acknowledge, even though §3.7 lists status first.
2. Rung 4 before rung 5. Body-FK existence is checked before request shape, so must_fk calls precede check_shape everywhere.
3. Revision ceiling refuses at revision_round >= 3 (PRD wording) rather than SCAFFOLD's <=.
4. Delivery tally uses §3.6's delivered + bounced == len(target_supporter_ids), not rung 24's "exceeds projected_reach" phrasing.
5. Activation block has no declared state-machine edge; allowed from PENDING or CLEARED with delivery_state == SCHEDULED, else ERR_INVALID_STATE_TRANSITION.
6. Posture-overrides never reject; the override is always stored and the CLOSED branch of the posture derivation wins.
7. Rung 8 is blanket. Acknowledge/thank/dispute/dispute-resolution/training-advancement/meeting-response/meeting-complete all require ACTIVE, since rung 8 "guards every write beneath a campaign" and lists no exemption for them.
8. Legislator creation writes the literal 0.00/MONITOR instead of running the pressure formula (which would yield 10.00 for UNDECIDED); the index first runs on the first mutation touching that row. Cascades therefore refresh only referenced legislators, never the whole campaign.
9. retention_score starts at 0.00 on supporter creation (SCAFFOLD default) while engagement_score gets the acquisition bonus (§3.2).
10. Ownership on partner withdraw is enforced (§2.1) although rung 6 names only four operations; likewise ERR_NOT_RESOURCE_OWNER is enforced for the Supporter role on the nested consent log, nested/flat spokesperson reads and single consent-event read.
11. ERR_NO_ELIGIBLE_VARIANT (no ladder rung) covers a named winner outside the cell, a cell with no LOCKED variant, and a named winner that is not LOCKED — checked before the 3-supporter reach floor.
12. Consent-event 404 reuses ERR_SUPPORTER_NOT_FOUND (no dedicated code exists in the twelve-family catalogue).
13. Adding a partner does not demote LOCKED variants — only withdrawal/revocation fire the demotion cascade; partner add only re-splits cost and recomputes quorum.
14. Endorsement rungs 8/9 are evaluated against the partner's campaign (first declared FK); a partner/variant campaign disagreement surfaces at rung 23 as ERR_CAMPAIGN_MISMATCH.
15. Thank-you frequency cap uses the BASE allowance of 3, never effective_touch_cap, and leaves engagement_score untouched.
16. An engagement_score change is a segment-membership cascade trigger (§3.4), so action create/dispute/resolve and training advancement all recompute segments → scheduled reach → activation revalidation → posture last.

## Step 5: Generate unit tests (subagent) — 2026-09-04T13:20:00.000Z

Subagent summary (verbatim):

Generation is complete. Everything is at the task root; workspace/implementation/ was never read or touched.

Files written (all absolute under tasks/task_2708_grassroots_advocacy_campaign_management/)

test_helpers/ — 2,837 lines, 9 files: __init__.py 21, api_client.py 350 (73 endpoint methods), api_errors.py 188, assertions.py 237, constants.py 389, factories.py 431, fixtures.py 844, test_users.py 148, types.py 229.

test_suite/ — 4,896 lines, 19 files: conftest.py 60; test_01_reach_and_value_divergence.py 220 (7 tests), test_02_combinatorial_formulas.py 218 (7), test_03_review_and_dispute_cycles.py 212 (6), test_04_transitive_cascades.py 261 (10), test_05_ladder_precedence.py 150 (4), test_06_boundaries.py 189 (7), test_07_collaborator_readiness.py 225 (7), test_08_temporal_overlap.py 246 (8), test_09_compensating_invariants.py 197 (8), test_10_entity_shapes.py 351 (12), test_11_state_machines.py 406 (12), test_12_calculations.py 417 (10), test_13_validations.py 803 (20), test_14_endpoints.py 230 (4), test_15_errors.py 99 (2), test_16_rbac.py 247 (5), test_17_complexity_layers.py 289 (4), test_18_consistency_model.py 76 (1).

Coverage
- 134 tests total. Queue A (difficulty): 64 tests over all 18/18 §1.8 instances (files 01–09 plus the queue-A part of the ladder work). Queue B (corner): 70 tests over all 70/70 non-stub §1.9 instances — entities 12, state_machines 12, calculations 10, validations 20, endpoints 4, errors 2, rbac 5, complexity layers 4, consistency model 1. The 16 excluded_because: stubs were not translated, as specified.
- Zero instances skipped — every non-stub instance passed the PRD-first two-condition filter.
- Validation: tests=134 tagged=134 problems=0 (every docstring carries exactly one final Design: line and every PRD: "…" citation survives a literal whitespace-normalised match against workspace/PRD.md); distinct tags=88 problems=0 (18 difficulty + 70 corner, 1:1, every tag resolving to a real name:); all 28 files ast.parse clean; all 18 test modules import under PYTHONPATH=.; pyflakes clean on the new files. No pytest run against a live server.

Partially-translated instances (design assertion weakened or dropped because the PRD does not uniquely derive it)
1. Corner/state_machines/action_record_with_no_legislator_in_the_district_becomes_unmatched — dropped contact_pressure_score == 10.00 (PRD 205: a new legislator starts at 0.00; PRD 302: an UNMATCHED action moves nothing).
2. Corner/state_machines/activation_clear_… — dropped send_cost_cents == 0 at creation; realized_reach asserted via assert_absent_or_none (PRD fixes both only at completion).
3. Corner/calculations/engagement_decay_holds_at_seven_days_… — re-based on the PRD-declared recompute trigger (action-record creation) with two supporters: 5.00 at exactly 7 days vs 4.25 at 8 days, instead of the design's 3.25. Boundary claim unchanged.
4. Corner/calculations/match_selector_… — both legislators asserted at 0.00 before the first action (PRD 205), not the design's 10.00.
5. Corner/validations/phone_action_for_an_email_only_supporter_returns_consent_missing — legislator 0.00, not the design's 10.00 (same reason).
6. Corner/validations/completion_tally_above_projected_reach_returns_delivery_tally_mismatch — dropped delivered_count == 0 and send_cost_cents == 0 on a still-SENDING wave; realized_reach via assert_absent_or_none.
7. Corner/validations/message_test_resolution_naming_an_unlocked_cell_returns_no_eligible_variant — dropped test_winner == false; the PRD never states that field's initial value.
8. Corner/rbac/the_submitting_user_cannot_record_the_review_decision_on_that_variant — asserted revision_round == 1, not the design's 0 (PRD 244: a new draft lands with revision_round 1; PRD 248 increments only on REQUEST_CHANGES).
9. Corner/cross-cutting complexity layers/every_write_increments_version_by_one_and_no_read_ever_does — the campaign version == 1 read is taken before the legislator is added rather than after, since the PRD does not state that legislator creation leaves the campaign row unmutated.

ORCHESTRATOR VERIFICATION: test_helpers/ and test_suite/ are both at the task root (not under workspace/); no stray copies inside workspace/.

## Step 7: Iterate tests + fixes (8-round parallel stability sweeps)

Iteration 1 — 8/8 rounds at 128/134, identical failure set (no flakiness):
1. `test_a_meeting_naming_a_legislator_of_another_campaign_is_a_scope_mismatch` — test asserted HTTP 409 for `ERR_CAMPAIGN_MISMATCH`; PRD §5 catalogues it at 422. Test fixed.
2. `test_a_meeting_starting_exactly_at_the_buffer_edge_is_accepted` and
3. `test_a_wave_starting_one_minute_after_the_last_close_gets_through` — both compared the echoed `window_start` string byte-for-byte against `...:00Z`; PRD pins only that a body timestamp is "parseable as ISO 8601 UTC" and never pins the echo form, so the assertions were re-expressed as instant comparisons (new `assert_instant_field` in test_helpers/assertions.py).
4. `test_the_rolling_engagement_score_halves_the_weight_of_forty_six_day_old_actions` — fixture jumped the clock 46 days and expected the read to re-score. PRD §2.5 says a clock call only changes the bucket used "on its next evaluation", and neither acknowledge nor close is a declared engagement trigger. Fixture now drives a declared trigger that leaves the counted rows identical (dispute + `REINSTATED` resolution on the email action).
5. `test_a_closed_campaign_refuses_lifecycle_calls_and_writes_beneath_it` and
6. `test_every_accepted_write_climbs_one_version_and_no_read_ever_does` — implementation bug: `common.touch` bumped `version` twice on the same row inside one request (the explicit status/override write plus `calc.refresh_posture`'s own touch when the derived posture changed). PRD §3.1/§3.9 both say the campaign's version "increments by 1" for override and close. `touch` is now idempotent per row per request while still refreshing `updated_at`.

Iteration 2 — 8/8 rounds at 134/134. Clean.

## Step 7: Run tests and iterate (long-lived subagent) — 2026-09-04T13:43:00.000Z

Subagent summary (verbatim):

Clean exit: 8/8 parallel rounds at 134/134 on iteration 2.

Iterations run: 2 (each an 8-round concurrent setsid nohup sweep, --isolation per-test-server).

Iteration 1 was 128/134 in all 8 rounds with a byte-identical failure set — no flakiness, six real defects.

Tests deleted: none. Every failing assertion traced to a verbatim PRD sentence and survived the unique-derivability check; all six were either a test mis-translation or an implementation bug.

Fixes applied to test_helpers/
- test_helpers/assertions.py — added assert_instant_field(entity, field, expected_iso), which compares parsed instants instead of raw strings. PRD rung 5 only requires a body timestamp be "parseable as ISO 8601 UTC" and never pins the echoed lexical form, so ...:00Z vs ...:00.000Z is format silence, not a defect.

Fixes applied to test_suite/
- test_10_entity_shapes.py:345 — validate_error(..., ERR_CAMPAIGN_MISMATCH, expected_status=409) → 422. PRD §5's error catalogue lists ERR_CAMPAIGN_MISMATCH at 422; the test hardcoded the wrong transport status.
- test_08_temporal_overlap.py:121,222 — the two window_start echo assertions now use assert_instant_field. The PRD-derivable claim (the accepted wave/meeting carries the requested instant) is preserved; the un-derivable string-format claim is gone.
- test_01_reach_and_value_divergence.py, fixture _supporter_with_two_forty_six_day_old_actions — the fixture jumped the clock 46 days and then expected a plain read to re-score. PRD §2.5 says a clock call changes only "the decay bucket ... on its next evaluation", and neither acknowledge (§3.7) nor close (§3.9, which writes only retention_score) is a declared engagement_score trigger. The fixture now drives a declared trigger that leaves the counted rows bit-identical — dispute the email action, then resolve it REINSTATED, both edges of which the PRD states recompute action_count, engagement_score and retention_score. Engagement then reads 4.00 and retention 6.00, exactly the PRD's worked example.

Fixes applied to implementation/
- workspace/implementation/common.py, touch() — made the version increment idempotent per row per request (tracked on Flask's g), while updated_at still follows the latest write. The row was being bumped twice whenever a request both wrote a field directly and had calc.refresh_posture change the derived posture of that same campaign — so POST .../posture-overrides and POST .../close each landed the campaign at +2. PRD §3.1 ("the override is stored, the posture is re-derived ... and the campaign's version increments by 1") and §3.9 ("the campaign's posture is set to FROZEN ... and the campaign's version increments by 1") both pin +1. This also removed a latent double-bump on supporters inside the close cascade (release-reservations touch plus retention-write touch).

ORCHESTRATOR VERIFICATION: I independently parsed all 8 results.$i.json myself (mtime 13:41) — every round reports passed=134, total=134. Sweep artifacts are present on disk, so the clean-sweep claim is confirmed rather than taken on report.

Step 8 is NOT skipped: Step 7 ran 2 iterations with 1 implementation/ fix, 3 test_suite/ fixes and 1 test_helpers/ fix.

## Step 8: Finalize PRD (subagent) — 2026-09-04T13:52:00.000Z

Step 8 was NOT skipped (Step 7 ran 2 iterations with fixes in all three layers).

Subagent summary (verbatim):

All three edits are applied. Verification of the file is complete.

PRD.md 469 lines / 113,829 B → PRD_FINALIZED.md 469 lines / 115,415 B. Line count unchanged (all edits are inline sentence insertions inside existing paragraphs); byte delta +1,586 B, +1.39 %.

Changes (3)
- §2.4 ¶1 — insert — pins the response rendering of every instant-valued field to the canonical YYYY-MM-DDTHH:MM:SS.mmmZ form (UTC, exactly three fractional digits) regardless of the lexical ISO 8601 form the client supplied, i.e. the server echoes the normalised instant, not the raw input string; nullable instants render null. — implementation/common.py:160-172 (fmt_dt), implementation/serializers.py:10-11,22-23,50-51,112-113,128,197-198,231-232,258-259, implementation/routes_campaign.py:57
- §2.4 ¶2 — insert — pins the version increment as once per row per request: a request that both writes a row directly and re-derives fields of that same row in its own cascade tail still advances that row's version by exactly 1, while updated_at follows every write. — implementation/common.py:246-271 (touch)
- §2.5 ¶2 — insert — pins that a clock call changes only the decay bucket: it does not rewrite any stored engagement_score, and a read of a supporter re-evaluates neither engagement_score nor retention_score. — implementation/routes_campaign.py:47-58 (set_clock refreshes milestone statuses only), implementation/serializers.py:78-99 (supporter_out is pure read-through)

No PRD edit for the ERR_CAMPAIGN_MISMATCH item: PRD §5 line 463 already lists it at 422 and common.py:88 agrees — that Step 7 fix was a pure test bug.

Per-edit pre-edit search log

Edit 1 — instant rendering
(a) Subject: the lexical form of every timestamp/instant the API emits, and whether client-supplied instants are echoed verbatim.
(b) Enumerated: common.py fmt_dt (single formatter, always 3 fractional digits + Z, None→None); common.py parse_dt/f_dt (input side accepts space separator, lowercase t/z, missing seconds, numeric offsets, naive → all normalised to UTC); grep of fmt_dt across all modules — every callsite is serializers.py plus common._meta (api_request_timestamp) and routes_campaign.py:57 (current_utc/previous_utc); read all 13 serializers to enumerate the full instant field set (created_at, updated_at, start_date, end_date, milestone/activation/meeting window_start/window_end, effective_at, acknowledged_at, thanked_at, last_refreshed_at). No route bypasses fmt_dt for an instant.
(c) Adjustment: deliberately restricted the claim to the output rendering and said only "whatever lexical ISO 8601 form the client wrote", instead of enumerating accepted input forms — parse_dt is far laxer than §2.8 rung 5's "parseable as ISO 8601 UTC", and pinning the input grammar would be a new, out-of-scope claim. Added the null-while-unset clause because three of the enumerated fields are nullable.

Edit 2 — version increment per request
(a) Subject: how many times one request may advance a single row's version.
(b) Enumerated: grepped every touch( callsite (60 across calc.py, cascades.py, routes_*.py) and every direct row["version"] write. Only new_row (=1), touch (+1) and two explicit resets (routes_supporter.py:133, routes_segment.py:76, which pin a freshly created row back to 1 after in-request derivations) write version. Read the multi-touch paths specifically: routes_campaign.set_posture_override (touch + refresh_posture on the same campaign), cascades.close_campaign (campaign touch + posture; supporters touched by reservation release, counter refresh and the retention write), cascades.abort_activation, cascades.complete_activation, calc.recompute_scheduled_reach, calc.refresh_cost_share, routes_coalition.withdraw_partner (partner touched by status write, cost-share and endorsement-count refresh). Also grepped every "version increments" sentence in the PRD (lines 207, 211, 217, 240, 246, 248, 252, 256, 258, 267, 275, 277, 281, 285, 291, 293, 295, 308, 310, 312, 314, 322, 326, 328, 333) — all state +1, none implies +2.
(c) Adjustment: scoped the sentence to the increment, not to the value a create returns — routes_coalition.create_partner lets refresh_cost_share touch the brand-new partner, so a created partner can serialize at version 2; a wording like "a row created by a request always reports 1" would have been a false universal. Left the pre-existing "begins at 1 on creation" clause verbatim. Also kept updated_at described as refreshed by every write (touch always restamps it), matching the "updated_at still follows the latest write" half of the Step 7 fix.

Edit 3 — score re-evaluation timing
(a) Subject: when a stored engagement_score/retention_score is rewritten, and whether reads re-derive them.
(b) Enumerated: routes_campaign.set_clock (touches only milestone statuses); calc.engagement_score/retention_score/refresh_supporter_counters and every caller (routes_action._recount_supporter on create/thank/dispute/dispute-resolution, routes_story.advance_training, cascades.abort_activation, cascades.close_campaign); routes_action.acknowledge_action (record-only, no supporter recompute); the read paths serializers.supporter_out, routes_supporter.get_supporter/list_supporters, calc.outcome_report (reads stored retention_score); and, for contrast, the two reads that do recompute — serializers.milestone_out (status) and serializers.variant_out (quorum), both already declared by the PRD and neither calling touch.
(c) Adjustment: scoped the "re-evaluates nothing" claim narrowly to a supporter read and to the two supporter score fields — a general "reads never recompute" would contradict milestone_out and variant_out. Also avoided asserting a closed list of recompute triggers ("until some later request recomputes that supporter's scores"), because close_campaign does in fact recompute engagement_score for supporters whose action records it voids, even though the PRD's close paragraph names only retention_score; a "close never touches engagement" wording would have been a brand-new mismatch.

ORCHESTRATOR VERIFICATION: PRD_FINALIZED.md exists at 115,415 B vs PRD.md at 113,829 B — not byte-identical, so the finalizer genuinely ran.

ORCHESTRATOR DECISION for Step 9: the implementation is 4,297 lines across 16 modules and the PRD is 469 long lines / 114 KB, which is too much for one subagent to scan exhaustively without truncating its own review. Step 9 will therefore run as THREE SEQUENTIAL module-partitioned passes over a single shared workspace/PRD_COMPLETED.md — pass 1 does the cp from PRD_FINALIZED.md, passes 2 and 3 must NOT re-copy (that would discard the previous pass's edits). Partition: pass 1 = the cross-cutting layer (common.py, gates.py, app.py, serializers.py, calc.py, cascades.py); pass 2 = routes_campaign.py, routes_calendar.py, routes_supporter.py, routes_segment.py; pass 3 = routes_variant.py, routes_coalition.py, routes_activation.py, routes_action.py, routes_story.py.

## Step 9: Complete PRD — three sequential module-partitioned passes (subagents) — 2026-09-04T14:39:00.000Z

Step 9 always runs. Executed as three sequential passes over one shared workspace/PRD_COMPLETED.md; pass 1 performed the cp from PRD_FINALIZED.md, passes 2 and 3 edited in place and were explicitly forbidden from re-copying.

### Pass 1 of 3 — cross-cutting layer (app.py, common.py, gates.py, serializers.py, calc.py, cascades.py)

Subagent summary (verbatim):

Setup confirmed: cp PRD_FINALIZED.md PRD_COMPLETED.md ran at the start of the pass.
Sizes: PRD_FINALIZED.md 469 lines / 115,415 chars → PRD_COMPLETED.md 469 lines / 121,136 chars, char delta +5,703. Line count and section structure are byte-stable (23 lines edited in place, no lines added/removed/reordered), so passes 2 and 3 can string-match safely.
Counts: 21 ambiguity-pins, 2 mismatch-revisions (23 edited lines total; a few lines carry more than one pin).

- §2.1 — revise — ambiguity — an auth header that is present but empty/whitespace-only is also ERR_UNAUTHENTICATED — common.py:338-341
- §2.2 — revise — ambiguity — api_request_id is req_ + twenty upper-case alphanumerics — common.py:282-286
- §2.2 — insert — ambiguity — api_request_timestamp reads real server time, not the logical clock — common.py:292
- §2.2 — insert — ambiguity — narrative note/reason inputs (override_reason, evidence_note, submission_note, review_note, reopen_reason, clearance_note, block_reason, acknowledgement_note, resolution_note, withdraw_reason, session_reference) are validated but never echoed; only revoked_reason/abort_reason/decline_reason/dispute_reason are published — serializers.py:176-236
- §2.2 — insert — ambiguity — unrouted path 404, unsupported method 405, server fault 500 all use the error envelope with ERR_INVALID_REQUEST — app.py:61-71
- §2.3 — revise — ambiguity — a non-integer limit/offset is ERR_INVALID_REQUEST — common.py:488-509
- §2.3 — insert — ambiguity — created_at ties resolve to server insertion order, never id; unknown query params ignored, blank filters treated as absent, boolean filters accept true/false/1/0 case-insensitively — common.py:274-275, 513-530
- §2.4 — insert — ambiguity — zone-less instants read as UTC, numeric offsets converted to UTC (offset never preserved) — common.py:180-196
- §2.5 — insert — ambiguity — recomputing a milestone status (clock move or read) bumps neither updated_at nor version — calc.py:396-403, serializers.py:45
- §2.6 — insert — ambiguity — trailing slash is not significant — app.py:52
- §2.6 — insert — ambiguity — an unresolvable consent_event_id reports ERR_SUPPORTER_NOT_FOUND — common.py:542
- §2.8 rung 4 — insert — ambiguity — a wrong-typed body FK yields that collection's 404, not a shape error; an absent key falls to rung 5 — common.py:554-575
- §2.8 rung 5 — insert — ambiguity — absent body read as {}; non-object body is ERR_INVALID_REQUEST; explicit null == absent; booleans never accepted for numbers — common.py:353-449
- §2.8 rung 14 — insert — ambiguity — an unrecognised lawful_basis is ERR_LAWFUL_BASIS_INVALID, not a rung-5 enum error, but the 40-char limit is rung 5 — gates.py:99-105
- §2.9 — insert — ambiguity — score family (plus rule_min_engagement_score) emitted as JSON numbers, so 60 prints 60.0 — common.py:225-229, serializers.py
- §2.10 — insert — ambiguity — a hop re-deriving a value to what it already held is not a mutation (no version/updated_at) — calc.py:230-235, 304-321, 359-374, 792-804
- §2.11 — revise — MISMATCH — blocked_activation_count counts approval_state == BLOCKED across every delivery state, so an aborted-while-blocked wave keeps counting — calc.py:754-760
- §2.11 — revise — MISMATCH — un-gating example changed from "aborting the second blocked wave" to "re-clearing" it, since abort never clears approval_state — cascades.py:87-97, routes_activation.py:217
- §2.12 — insert — ambiguity — cascade reach re-derivation releases all affected reservations then retakes them in created_at order (earliest wave has first claim) — calc.py:669-700
- §3.3 — insert — ambiguity — the read-time quorum re-derivation bumps neither version nor updated_at — serializers.py:134-136
- §3.4 — insert — ambiguity — the system-triggered LOCKED → CHANGES_REQUESTED demotion still increments revision_round and still blocks waves — cascades.py:32-36
- §3.5 — insert — ambiguity — only the explicit refresh endpoint stamps last_refreshed_at; cascade recomputation leaves it (so it stays null) — calc.py:588-613 vs routes_segment.py:129
- §3.5 — insert — ambiguity — a freshly scheduled wave's realized_reach/delivered_count/bounced_count/abort_reason are null while send_cost_cents/suppressed_by_consent_count are 0 — serializers.py:205-216
- §3.6 — revise — MISMATCH (same subject as the §2.11 revision) — abort does not decrement blocked_activation_count; it leaves approval_state untouched — cascades.py:87-114

Verified-clean areas needing no change: the §5 error catalogue matches ERROR_HTTP entry-for-entry (all 51); every calc constant, cap, tie-break, rounding direction and threshold matches the §2.9/§3.x prose; refresh_posture's six branches, outcome_report's thirteen values, the funding-split floor-then-distribute order, quorum ceiling, consent replay, decay buckets, and the cascade() posture-last discipline are all already uniquely pinned. One prospective edit was dropped after checking impl: rule_min_engagement_score IS rounded to 2dp on input (routes_segment.py:65), so no "stored verbatim" claim was added.

### Pass 2 of 3 — routes_campaign.py, routes_calendar.py, routes_supporter.py, routes_segment.py

Subagent summary (verbatim):

No copy performed — I edited workspace/PRD_COMPLETED.md in place with 18 targeted Edit calls. Pass 1's clauses (e.g. the §2.4 "counted once per row per request" clause, the §2.5 "a read of a supporter re-evaluates neither score" clause) are intact; heading list and §4/§5 table row counts are byte-for-byte structurally identical to before.
Before first edit: 469 lines / 121,136 chars. After last edit: 469 lines / 126,266 chars.
Counts: 14 ambiguity-pins, 4 mismatch-revisions.

- §2.3 — revise — MISMATCH — the cross-supporter consent-event audit list is also ordered created_at→sequence_no (insertion order is only the third key), so "elsewhere = insertion order" no longer over-claims — routes_supporter.py:225
- §2.3 — insert — ambiguity — enum-valued filters are never validated; an out-of-enum status/posture/kind/stance/priority_tier/acquisition_source/channel/action matches nothing instead of erroring — routes_campaign.py:141, routes_calendar.py:98
- §2.5 — insert — ambiguity — the clock accepts any parseable instant including one earlier than the current value; previous_utc is the displaced value (startup default on the first call); the payload carries nothing else — routes_campaign.py:52
- §2.8 rung 5 — revise — MISMATCH — rung 5 applies only to endpoints declaring at least one field; bodyless transitions (launch, close, segment refresh) read no body at all and ignore anything sent — routes_campaign.py:148, routes_campaign.py:161, routes_segment.py:103
- §2.8 rung 6 — revise — MISMATCH — "exactly four operations" was false: the ownership rung also guards owner-scoped reads (a supporter's consent log, a single consent event, a supporter's spokesperson profiles), after rung 3 — routes_supporter.py:170,183,242
- §3.1 — insert — ambiguity — an end_date not strictly after start_date is ERR_INVALID_REQUEST (not ERR_INVALID_WINDOW), and campaign bounds need no whole-minute alignment — routes_campaign.py:98
- §3.1 — insert — ambiguity — launch preconditions are ordered: a non-DRAFT campaign yields ERR_INVALID_STATE_TRANSITION before the legislator list is consulted — routes_campaign.py:151
- §3.1 — insert — ambiguity — a stance update restating the current stance is accepted and still bumps the legislator's version by 1; no stance is an illegal successor — routes_calendar.py:209
- §3.1 — revise — MISMATCH — a posture override on a CLOSED campaign is accepted and stored (posture stays FROZEN); the endpoint has no lifecycle precondition and never returns ERR_CAMPAIGN_NOT_ACTIVE/ERR_INVALID_STATE_TRANSITION — routes_campaign.py:176-189
- §3.1 — insert — ambiguity — a milestone's status is clock-derived at creation (can be born IN_WINDOW/PASSED), and creation runs no cascade, so a new RECESS does not block existing scheduled waves — routes_calendar.py:74, routes_calendar.py:60-76
- §3.1 — insert — ambiguity — the global milestone list recomputes every status before filtering, so the status filter matches recomputed positions — routes_calendar.py:94
- §3.2 — insert — ambiguity — email max length 200 — routes_supporter.py:84
- §3.2 — insert — ambiguity — phone max length 32, and an ALL-scoped initial grant does not itself require a phone — routes_supporter.py:87,97
- §3.2 — insert — ambiguity — initial_consent_channels accepts EMAIL/SMS/PHONE/ALL, and an explicitly empty array captures nothing — routes_supporter.py:88
- §3.2 — insert — ambiguity — retention_score starts 0.00 (not source-seeded), and supporter creation runs the full audience cascade (segments → reach/reservations → re-validate → posture) while still returning version 1 — routes_supporter.py:123,131-135
- §3.5 — insert — ambiguity — rule_district_codes entries max 16 chars; a negative rule_min_engagement_score is ERR_INVALID_REQUEST and a finer-grained value is rounded half up to 2 dp on store — routes_segment.py:52-66
- §3.5 — insert — ambiguity — an explicit refresh bumps version unconditionally even when membership is unchanged, and cascades into scheduled-wave reach, re-validation, active_activation_count and posture — routes_segment.py:129-132
- §4 — revise — ambiguity — the message-test-resolution row now states the response is the winning variant, not the campaign — routes_campaign.py:231

Note for pass 3: resolve_message_test physically lives in routes_campaign.py (pass 2's file) though its subject is §3.4; pass 2 audited it and found only the response-payload silence worth pinning — its guard order (cell membership → cell has a LOCKED → winner LOCKED → reach floor) already matches §3.4 and rung 24.

### Pass 3 of 3 — routes_variant.py, routes_coalition.py, routes_activation.py, routes_action.py, routes_story.py

Subagent summary (verbatim):

All 23 pass-3 edits verified present in workspace/PRD_COMPLETED.md (each anchor string matches exactly once). PASS 3 OF 3 complete.
No copy performed. I never ran cp, never issued a whole-file Write, and made only targeted Edit calls. Prior passes' clauses are intact (cumulative diff vs PRD_FINALIZED.md is 106 changed lines, spanning all three passes).
Counts — before my first edit: 469 lines / 126266 chars. After my last edit: 469 lines / 131142 chars. (PRD_FINALIZED.md baseline for reference: 469 lines / 115415 chars.)
14 ambiguity-pins, 9 mismatch-revisions.

Ambiguity pins:
- §2.8 rung 5 — insert — ambiguity — variant lock and send start read no request body at all, so rung 5 is vacuous for them — routes_variant.py:159, routes_activation.py:241
- §3.3 — insert — ambiguity — partner add re-derives quorum on every variant of the campaign, bumps moved variants' version, and never demotes a LOCKED variant — routes_coalition.py:66
- §3.4 — insert — ambiguity — variant create defaults: null submitter/reviewer, endorsement_count 0, test_winner false, metrics 0, cost_per_action_cents sentinel 999999, revision_round 1 — routes_variant.py:57-79
- §3.4 — insert — ambiguity — channel_scope stored verbatim; duplicate entries neither de-duplicated nor rejected — routes_variant.py:53
- §3.4 — insert — ambiguity — resubmission stamps submitted_by_user_id but does not clear reviewed_by_user_id — routes_variant.py:131
- §3.4 — insert — ambiguity — endorsement create re-derives quorum, never moves variant status, runs no wave/posture hop — routes_coalition.py:186
- §3.4 — insert — ambiguity — lock re-derives quorum immediately before the comparison rather than trusting the stored value — routes_variant.py:167
- §3.5 — insert — ambiguity — block requires SCHEDULED + PENDING/CLEARED and is gated on neither posture nor SoD — routes_activation.py:231
- §3.7 — insert — ambiguity — activation_id accepted whatever delivery_state the wave holds — routes_action.py:75
- §3.7 — insert — ambiguity — full ordered propagation tail (legislator, supporter recount, segment membership, reach, revalidation, activation counts, posture), shared by dispute and dispute-resolution — routes_action.py:53
- §3.7 — insert — ambiguity — dispute_reason retained on REINSTATED as audit trail — routes_action.py:212
- §3.8 — insert — ambiguity — both training rungs carry the reach/revalidate/activation-count/posture tail — routes_story.py:139
- §3.8 — insert — ambiguity — meeting create writes attendee_count and decline_reason null — routes_story.py:205
- §3.8 — insert — ambiguity — decline_reason read then ignored on the CONFIRM edge — routes_story.py:244

Mismatch revisions:
- §2.1 — revise — MISMATCH — FieldOrganizer's "exclusively theirs" corrected: CampaignDirector is authorised alongside on all five calls — routes_action.py:135,151; routes_story.py:111,241,267
- §2.8 rung 6 — revise — MISMATCH — four writes → five (partner withdrawal added) plus one owner-scoped read (spokesperson profile fetch) — routes_coalition.py:102; routes_story.py:90
- §2.8 rung 21 — revise — MISMATCH — ERR_REVISION_LIMIT_REACHED guards submission AND operator-triggered reopen, not submission only — routes_variant.py:191
- §2.8 rung 24 — revise — MISMATCH — ERR_FREQUENCY_CAP_EXHAUSTED fires for any empty target list, not only the touch-cap cause — routes_activation.py:131
- §2.8 rung 24 — revise — MISMATCH — tally rule is exact-sum equality in both directions (too many or too few), not "delivered_count exceeds projected_reach" — routes_activation.py:275
- §3.3 — revise — MISMATCH — withdrawal hops 1-3 corrected: partner's active_endorsement_count → 0, quorum recomputed on every variant, demotion sweep over every variant — routes_coalition.py:118-128
- §3.4 — revise — MISMATCH — RETIRED is terminal on the review ladder, but endorsement creation does not police variant status, so a RETIRED variant can still be endorsed — routes_coalition.py:139
- §3.5 — revise — MISMATCH — system-BLOCKED trigger list extended with spokesperson training advance and action-record writes — routes_action.py:53; routes_story.py:139
- §3.7 — revise — MISMATCH — thank-you preconditions reordered to ladder order (FROZEN before record state) — routes_action.py:159-169

Final integrity check: PASS.
- wc -l -c → 469 lines, 131142 chars; no line-count change (all edits inline).
- grep -n "^#" → title (1), ## 1. Introduction (3), ## 2. (11) with §2.1-§2.12, ## 3. Business Logic & Workflows (197) with §3.1-§3.9, ## 4. Endpoint Definitions (339), ## 5. Error Code Catalogue (416) — all present, in order.
- §4 endpoint table: 70 data rows.
- §5 error table: 50 rows (complete set, matches common.py ERROR_HTTP).
- Final line is a complete markdown table row — | `ERR_DELIVERY_TALLY_MISMATCH` | 409 | — no truncation.

Scope notes: pass 3 audited only routes_variant.py, routes_coalition.py, routes_activation.py, routes_action.py, routes_story.py, and left pass-1/pass-2 territory (including resolve_message_test) untouched. Three apparent gaps were deliberately not edited after verifying they are unobservable through any response or serialized field: the unconditional touch in _recount_supporter, refresh_posture on send start, and refresh_variant_metrics_of sweeping all variants on abort. No SCAFFOLD*.yaml, worklog.md, or sibling task directory was read.

### ORCHESTRATOR FINAL VERIFICATION — 2026-09-04T14:40:00.000Z

- PRD.md 469 lines / 113,829 B → PRD_FINALIZED.md 469 lines / 115,415 B → PRD_COMPLETED.md 469 lines / 131,142 B. `cmp` confirms PRD_COMPLETED.md is NOT byte-identical to PRD_FINALIZED.md (the three passes genuinely ran); `diff` shows 106 changed lines cumulatively.
- Step 9 totals across the three passes: 49 ambiguity-pins, 15 mismatch-revisions, 64 edits, zero new sections and zero line-count change.
- PRD_COMPLETED.md ends on a complete markdown table row; all of §1–§5 present in order; §4 has 70 endpoint rows and §5 has 50 error rows.
- Final 8-round sweep artifacts re-parsed by the orchestrator: results.1..8.json all report 134/134.
- Only one worklog.md exists (task root); no stray copy drifted into workspace/.

PIPELINE COMPLETE.
