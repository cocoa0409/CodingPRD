import { v4 as uuidv4 } from 'uuid';
import {
  getAs,
  postAs,
  putWithVersion,
  postWithVersion,
  postAction
} from './api-client';
import { expectSuccess } from './assertions';
import {
  ContentRating,
  CONTENT_RATING,
  BrandTier,
  BRAND_TIER,
  DealStatus,
  DEAL_STATUS,
  Placement,
  PLACEMENT,
  ClaimKind,
  ClaimOutcome,
  DEFAULT_AD_CAPACITY_SECONDS,
  DEFAULT_AD_SLOTS_TOTAL_SECONDS,
  DEFAULT_BUDGET_TOTAL_CENTS,
  DEFAULT_SLOT_PRICE_CENTS,
} from './constants';

export function uniqueId(prefix: string = 'test'): string {
  return `${prefix}-${uuidv4().slice(0, 8)}`;
}

export function unwrap<T = any>(body: any): T {
  return (body && typeof body === 'object' && 'data' in body) ? body.data : body;
}

export function pickId(body: any, keys: string[]): string {
  for (const key of keys) {
    const value = body?.[key];
    if (typeof value === 'string' && value.length > 0) return value;
  }
  throw new Error(`Could not find id in response. Looked for: ${keys.join(', ')}`);
}

export function asArray(value: any): any[] {
  if (Array.isArray(value)) return value;
  if (Array.isArray(value?.items)) return value.items;
  if (Array.isArray(value?.data)) return value.data;
  return [];
}

export interface Podcast {
  id: string;
  name: string;
  ad_capacity_seconds: number;
  posture: string;
  open_claim_count: number;
  ops_run_index: number;
  ad_held_seconds: number;
  ad_committed_seconds: number;
  ad_available_seconds: number;
  version?: number;
}

export interface Episode {
  id: string;
  title: string;
  content_rating: ContentRating;
  status: string;
  clearance: string;
  ad_slots_total_seconds: number;
  ad_slots_held_seconds: number;
  ad_slots_committed_seconds: number;
  reservations?: Reservation[];
  version: number;
}

export interface Deal {
  id: string;
  advertiser_name: string;
  brand_tier: BrandTier;
  status: DealStatus;
  budget_total_cents: number;
  budget_held_cents: number;
  budget_committed_cents: number;
  budget_spent_cents: number;
  budget_available_cents: number;
  slot_price_cents: number;
  script_text: string;
  script_version: number;
  version: number;
}

export interface Reservation {
  id: string;
  episode_id: string;
  deal_id: string;
  placement: Placement;
  slot_seconds: number;
  status: string;
  script_version_pinned?: number;
  version: number;
}

export interface Claim {
  id: string;
  episode_id: string;
  kind: ClaimKind;
  status: string;
  outcome?: ClaimOutcome;
  version: number;
}

export interface CreatePodcastInput {
  name?: string;
  ad_capacity_seconds?: number;
}

export interface CreateEpisodeInput {
  title?: string;
  content_rating?: ContentRating;
  ad_slots_total_seconds?: number;
}

export interface UpdateEpisodeInput {
  title?: string;
  content_rating?: ContentRating;
  ad_slots_total_seconds?: number;
}

export interface CreateDealInput {
  advertiser_name?: string;
  brand_tier?: BrandTier;
  budget_total_cents?: number;
  slot_price_cents?: number;
  script_text?: string;
}

export interface UpdateDealInput {
  status?: DealStatus;
  script_text?: string;
  brand_tier?: BrandTier;
}

export interface CreateReservationInput {
  episode_id: string;
  deal_id: string;
  placement?: Placement;
  slot_seconds?: number;
}

export interface CreateClaimInput {
  episode_id: string;
  kind: ClaimKind;
}

export async function createPodcast(input: CreatePodcastInput = {}): Promise<Podcast> {
  const payload = {
    name: input.name ?? uniqueId('Podcast'),
    ad_capacity_seconds: input.ad_capacity_seconds ?? DEFAULT_AD_CAPACITY_SECONDS,
  };
  const res = await postAs('/podcasts', payload);
  expectSuccess(res);
  return unwrap(res.body);
}

export async function getPodcast(podcastId: string): Promise<Podcast> {
  const res = await getAs(`/podcasts/${podcastId}`);
  expectSuccess(res);
  return unwrap(res.body);
}

export async function runOps(podcastId: string, version: number | string): Promise<any> {
  const res = await postWithVersion(`/podcasts/${podcastId}/run_ops`, {}, version);
  expectSuccess(res);
  return unwrap(res.body);
}

export async function createEpisode(
  podcastId: string,
  input: CreateEpisodeInput = {}
): Promise<Episode> {
  const payload = {
    title: input.title ?? uniqueId('Episode'),
    content_rating: input.content_rating ?? CONTENT_RATING.GENERAL,
    ad_slots_total_seconds: input.ad_slots_total_seconds ?? DEFAULT_AD_SLOTS_TOTAL_SECONDS,
  };
  const res = await postAs(`/podcasts/${podcastId}/episodes`, payload);
  expectSuccess(res);
  return unwrap(res.body);
}

export async function getEpisode(podcastId: string, episodeId: string): Promise<Episode> {
  const res = await getAs(`/podcasts/${podcastId}/episodes/${episodeId}`);
  expectSuccess(res);
  return unwrap(res.body);
}

export async function updateEpisode(
  podcastId: string,
  episodeId: string,
  version: number | string,
  input: UpdateEpisodeInput
): Promise<Episode> {
  const res = await putWithVersion(
    `/podcasts/${podcastId}/episodes/${episodeId}`,
    input,
    version
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function submitEpisode(
  podcastId: string,
  episodeId: string,
  version: number | string
): Promise<Episode> {
  const res = await postAction(
    `/podcasts/${podcastId}/episodes/${episodeId}/submit`,
    version
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function publishEpisode(
  podcastId: string,
  episodeId: string,
  version: number | string
): Promise<Episode> {
  const res = await postAction(
    `/podcasts/${podcastId}/episodes/${episodeId}/publish`,
    version
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function retractEpisode(
  podcastId: string,
  episodeId: string,
  version: number | string
): Promise<Episode> {
  const res = await postAction(
    `/podcasts/${podcastId}/episodes/${episodeId}/retract`,
    version
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function createDeal(
  podcastId: string,
  input: CreateDealInput = {}
): Promise<Deal> {
  const payload = {
    advertiser_name: input.advertiser_name ?? uniqueId('Advertiser'),
    brand_tier: input.brand_tier ?? BRAND_TIER.STANDARD,
    budget_total_cents: input.budget_total_cents ?? DEFAULT_BUDGET_TOTAL_CENTS,
    slot_price_cents: input.slot_price_cents ?? DEFAULT_SLOT_PRICE_CENTS,
    script_text: input.script_text ?? 'Default script v1',
  };
  const res = await postAs(`/podcasts/${podcastId}/deals`, payload);
  expectSuccess(res);
  return unwrap(res.body);
}

export async function getDeal(podcastId: string, dealId: string): Promise<Deal> {
  const res = await getAs(`/podcasts/${podcastId}/deals/${dealId}`);
  expectSuccess(res);
  return unwrap(res.body);
}

export async function updateDeal(
  podcastId: string,
  dealId: string,
  version: number | string,
  input: UpdateDealInput
): Promise<Deal> {
  const res = await putWithVersion(
    `/podcasts/${podcastId}/deals/${dealId}`,
    input,
    version
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function activateDeal(
  podcastId: string,
  dealId: string,
  version: number | string
): Promise<Deal> {
  return updateDeal(podcastId, dealId, version, { status: DEAL_STATUS.ACTIVE });
}

export async function pauseDeal(
  podcastId: string,
  dealId: string,
  version: number | string
): Promise<Deal> {
  return updateDeal(podcastId, dealId, version, { status: DEAL_STATUS.PAUSED });
}

export async function closeDeal(
  podcastId: string,
  dealId: string,
  version: number | string
): Promise<Deal> {
  return updateDeal(podcastId, dealId, version, { status: DEAL_STATUS.CLOSED });
}

export async function createReservation(
  podcastId: string,
  input: CreateReservationInput
): Promise<Reservation> {
  const payload = {
    episode_id: input.episode_id,
    deal_id: input.deal_id,
    placement: input.placement ?? PLACEMENT.PRE_ROLL,
    slot_seconds: input.slot_seconds ?? 30,
  };
  const res = await postAs(`/podcasts/${podcastId}/reservations`, payload);
  expectSuccess(res);
  return unwrap(res.body);
}

export async function approveReservation(
  podcastId: string,
  reservationId: string,
  version: number | string
): Promise<Reservation> {
  const res = await postAction(
    `/podcasts/${podcastId}/reservations/${reservationId}/approve`,
    version
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function cancelReservation(
  podcastId: string,
  reservationId: string,
  version: number | string
): Promise<Reservation> {
  const res = await postAction(
    `/podcasts/${podcastId}/reservations/${reservationId}/cancel`,
    version
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function settleReservation(
  podcastId: string,
  reservationId: string,
  version: number | string
): Promise<Reservation> {
  const res = await postAction(
    `/podcasts/${podcastId}/reservations/${reservationId}/settle`,
    version
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export function findReservation(episode: Episode, reservationId: string): Reservation | undefined {
  return episode.reservations?.find(r => r.id === reservationId);
}

export async function createClaim(
  podcastId: string,
  input: CreateClaimInput
): Promise<Claim> {
  const payload = {
    episode_id: input.episode_id,
    kind: input.kind,
  };
  const res = await postAs(`/podcasts/${podcastId}/claims`, payload);
  expectSuccess(res);
  return unwrap(res.body);
}

export async function closeClaim(
  podcastId: string,
  claimId: string,
  version: number | string,
  outcome: ClaimOutcome
): Promise<Claim> {
  const res = await postWithVersion(
    `/podcasts/${podcastId}/claims/${claimId}/close`,
    { outcome },
    version
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export interface FixtureStackGeneralStd {
  podcast: Podcast;
  episode: Episode;
  deal: Deal;
}

export async function createFixtureStackGeneralStd(): Promise<FixtureStackGeneralStd> {
  const podcast = await createPodcast({ name: 'PodLab', ad_capacity_seconds: 180 });
  const episode = await createEpisode(podcast.id, {
    title: 'Ep1',
    content_rating: CONTENT_RATING.GENERAL,
    ad_slots_total_seconds: 60,
  });
  const deal = await createDeal(podcast.id, {
    advertiser_name: 'Acme',
    brand_tier: BRAND_TIER.STANDARD,
    budget_total_cents: 5000,
    slot_price_cents: 1000,
    script_text: 'Read v1',
  });
  const activatedDeal = await activateDeal(podcast.id, deal.id, deal.version);

  return { podcast, episode, deal: activatedDeal };
}

export interface FixtureStackGeneralFamily {
  podcast: Podcast;
  episode: Episode;
  deal: Deal;
}

export async function createFixtureStackGeneralFamily(): Promise<FixtureStackGeneralFamily> {
  const podcast = await createPodcast({ name: 'FamPod', ad_capacity_seconds: 180 });
  const episode = await createEpisode(podcast.id, {
    title: 'Ep1',
    content_rating: CONTENT_RATING.GENERAL,
    ad_slots_total_seconds: 60,
  });
  const deal = await createDeal(podcast.id, {
    advertiser_name: 'KidCo',
    brand_tier: BRAND_TIER.FAMILY_SAFE,
    budget_total_cents: 3000,
    slot_price_cents: 1000,
    script_text: 'Kids v1',
  });
  const activatedDeal = await activateDeal(podcast.id, deal.id, deal.version);

  return { podcast, episode, deal: activatedDeal };
}

export interface FixtureStackMatureFamily {
  podcast: Podcast;
  episode: Episode;
  deal: Deal;
}

export async function createFixtureStackMatureFamily(): Promise<FixtureStackMatureFamily> {
  const podcast = await createPodcast({ name: 'MaturePod', ad_capacity_seconds: 180 });
  const episode = await createEpisode(podcast.id, {
    title: 'EpM',
    content_rating: CONTENT_RATING.MATURE,
    ad_slots_total_seconds: 60,
  });
  const deal = await createDeal(podcast.id, {
    advertiser_name: 'KidCo',
    brand_tier: BRAND_TIER.FAMILY_SAFE,
    budget_total_cents: 3000,
    slot_price_cents: 1000,
    script_text: 'Kids v1',
  });
  const activatedDeal = await activateDeal(podcast.id, deal.id, deal.version);

  return { podcast, episode, deal: activatedDeal };
}

export interface FixtureStackLiveStd {
  podcast: Podcast;
  episode: Episode;
  deal: Deal;
}

export async function createFixtureStackLiveStd(): Promise<FixtureStackLiveStd> {
  const podcast = await createPodcast({ name: 'LivePod', ad_capacity_seconds: 180 });
  let episode = await createEpisode(podcast.id, {
    title: 'EpLive',
    content_rating: CONTENT_RATING.GENERAL,
    ad_slots_total_seconds: 60,
  });
  episode = await submitEpisode(podcast.id, episode.id, episode.version);
  episode = await publishEpisode(podcast.id, episode.id, episode.version);

  const deal = await createDeal(podcast.id, {
    advertiser_name: 'Acme',
    brand_tier: BRAND_TIER.STANDARD,
    budget_total_cents: 5000,
    slot_price_cents: 1000,
    script_text: 'Read v1',
  });
  const activatedDeal = await activateDeal(podcast.id, deal.id, deal.version);

  return { podcast, episode, deal: activatedDeal };
}

export interface FixtureStackTightCapacity {
  podcast: Podcast;
  episode: Episode;
  deal: Deal;
}

export async function createFixtureStackTightCapacity(): Promise<FixtureStackTightCapacity> {
  const podcast = await createPodcast({ name: 'TightCast', ad_capacity_seconds: 60 });
  const episode = await createEpisode(podcast.id, {
    title: 'EpTight',
    content_rating: CONTENT_RATING.GENERAL,
    ad_slots_total_seconds: 60,
  });
  const deal = await createDeal(podcast.id, {
    advertiser_name: 'Acme',
    brand_tier: BRAND_TIER.STANDARD,
    budget_total_cents: 5000,
    slot_price_cents: 1000,
    script_text: 'Read v1',
  });
  const activatedDeal = await activateDeal(podcast.id, deal.id, deal.version);

  return { podcast, episode, deal: activatedDeal };
}

export interface FixtureHoldPre30 {
  podcast: Podcast;
  episode: Episode;
  deal: Deal;
  reservation: Reservation;
}

export async function createFixtureHoldPre30(): Promise<FixtureHoldPre30> {
  const { podcast, episode, deal } = await createFixtureStackGeneralStd();
  const reservation = await createReservation(podcast.id, {
    episode_id: episode.id,
    deal_id: deal.id,
    placement: PLACEMENT.PRE_ROLL,
    slot_seconds: 30,
  });

  return { podcast, episode, deal, reservation };
}

export interface FixtureApprovedPre30 {
  podcast: Podcast;
  episode: Episode;
  deal: Deal;
  reservation: Reservation;
}

export async function createFixtureApprovedPre30(): Promise<FixtureApprovedPre30> {
  const { podcast, episode, deal, reservation } = await createFixtureHoldPre30();
  const approvedReservation = await approveReservation(podcast.id, reservation.id, reservation.version);

  return { podcast, episode, deal, reservation: approvedReservation };
}

export interface FixtureHoldPre60 {
  podcast: Podcast;
  episode: Episode;
  deal: Deal;
  reservation: Reservation;
}

export async function createFixtureHoldPre60(): Promise<FixtureHoldPre60> {
  const { podcast, episode, deal } = await createFixtureStackGeneralStd();
  const reservation = await createReservation(podcast.id, {
    episode_id: episode.id,
    deal_id: deal.id,
    placement: PLACEMENT.PRE_ROLL,
    slot_seconds: 60,
  });

  return { podcast, episode, deal, reservation };
}

export interface FixtureApprovedPre60 {
  podcast: Podcast;
  episode: Episode;
  deal: Deal;
  reservation: Reservation;
}

export async function createFixtureApprovedPre60(): Promise<FixtureApprovedPre60> {
  const { podcast, episode, deal, reservation } = await createFixtureHoldPre60();
  const approvedReservation = await approveReservation(podcast.id, reservation.id, reservation.version);

  return { podcast, episode, deal, reservation: approvedReservation };
}

export interface FixtureSettledPre30 {
  podcast: Podcast;
  episode: Episode;
  deal: Deal;
  reservation: Reservation;
}

export async function createFixtureSettledPre30(): Promise<FixtureSettledPre30> {
  const { podcast, episode, deal } = await createFixtureStackLiveStd();

  const reservation = await createReservation(podcast.id, {
    episode_id: episode.id,
    deal_id: deal.id,
    placement: PLACEMENT.PRE_ROLL,
    slot_seconds: 30,
  });
  const approved = await approveReservation(podcast.id, reservation.id, reservation.version);
  const settled = await settleReservation(podcast.id, reservation.id, approved.version);

  return { podcast, episode, deal, reservation: settled };
}

export interface FixtureClaimRightsOpen {
  podcast: Podcast;
  episode: Episode;
  deal: Deal;
  claim: Claim;
}

export async function createFixtureClaimRightsOpen(): Promise<FixtureClaimRightsOpen> {
  const { podcast, episode, deal } = await createFixtureStackLiveStd();
  const claim = await createClaim(podcast.id, {
    episode_id: episode.id,
    kind: 'RIGHTS',
  });

  return { podcast, episode, deal, claim };
}

export interface FixtureRestrictedTwoOpenClaims {
  podcast: Podcast;
  episode1: Episode;
  episode2: Episode;
  claim1: Claim;
  claim2: Claim;
}

export async function createFixtureRestrictedTwoOpenClaims(): Promise<FixtureRestrictedTwoOpenClaims> {
  const podcast = await createPodcast({ name: 'ClaimPod', ad_capacity_seconds: 180 });
  const episode1 = await createEpisode(podcast.id, {
    title: 'EpA',
    content_rating: CONTENT_RATING.GENERAL,
    ad_slots_total_seconds: 60,
  });
  const episode2 = await createEpisode(podcast.id, {
    title: 'EpB',
    content_rating: CONTENT_RATING.GENERAL,
    ad_slots_total_seconds: 60,
  });
  const claim1 = await createClaim(podcast.id, {
    episode_id: episode1.id,
    kind: 'RIGHTS',
  });
  const claim2 = await createClaim(podcast.id, {
    episode_id: episode2.id,
    kind: 'BRAND_SAFETY',
  });

  return { podcast, episode1, episode2, claim1, claim2 };
}

export interface FixtureAcceptedClaimAuditPending {
  podcast: Podcast;
  episode: Episode;
  deal: Deal;
  reservation: Reservation;
  claim: Claim;
}

export async function createFixtureAcceptedClaimAuditPending(): Promise<FixtureAcceptedClaimAuditPending> {
  const { podcast, episode, deal, reservation } = await createFixtureSettledPre30();

  const claim = await createClaim(podcast.id, {
    episode_id: episode.id,
    kind: 'RIGHTS',
  });
  const closedClaim = await closeClaim(podcast.id, claim.id, claim.version, 'ACCEPTED');

  return { podcast, episode, deal, reservation, claim: closedClaim };
}

export async function createAndApproveReservation(
  podcastId: string,
  input: CreateReservationInput
): Promise<Reservation> {
  const reservation = await createReservation(podcastId, input);
  return approveReservation(podcastId, reservation.id, reservation.version);
}

export async function createApproveAndSettleReservation(
  podcastId: string,
  input: CreateReservationInput
): Promise<Reservation> {
  const reservation = await createReservation(podcastId, input);
  const approved = await approveReservation(podcastId, reservation.id, reservation.version);
  return settleReservation(podcastId, reservation.id, approved.version);
}

export async function submitAndPublishEpisode(
  podcastId: string,
  episodeId: string,
  version: number | string
): Promise<Episode> {
  const submitted = await submitEpisode(podcastId, episodeId, version);
  return publishEpisode(podcastId, episodeId, submitted.version);
}

export async function createAndActivateDeal(
  podcastId: string,
  input: CreateDealInput = {}
): Promise<Deal> {
  const deal = await createDeal(podcastId, input);
  return activateDeal(podcastId, deal.id, deal.version);
}
