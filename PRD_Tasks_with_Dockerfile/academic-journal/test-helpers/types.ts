export interface ResponseMetaBase {

  api_request_id: string;

  api_request_timestamp: string;
}

export interface PaginationMeta {
  limit: number;
  offset: number;
  total_count: number;
  has_more: boolean;
}

export type SuccessResponseType = 'object' | 'array';
export type ErrorResponseType = 'error';

export interface ApiSuccessEnvelope<T> {
  meta: ResponseMetaBase & Partial<PaginationMeta>;
  response_type: SuccessResponseType;
  data: T;
}

export interface ErrorResponseData {

  error_id: string;

  message: string;

  details?: Array<{ field: string; issue: string }>;
}

export interface ApiErrorEnvelope {
  meta: ResponseMetaBase;
  response_type: ErrorResponseType;
  data: ErrorResponseData;
}

export type ApiResponse<T> = ApiSuccessEnvelope<T> | ApiErrorEnvelope;

export enum UserRole {
  JournalEditor = 'JournalEditor',
  SectionEditor = 'SectionEditor',
  ManagingEditor = 'ManagingEditor',
}

export enum JournalStatus {
  ACCEPTING_SUBMISSIONS = 'ACCEPTING_SUBMISSIONS',
  IN_REVIEW = 'IN_REVIEW',
  PUBLICATION_PENDING = 'PUBLICATION_PENDING',
  ARCHIVED = 'ARCHIVED',
}

export enum ManuscriptStatus {
  DRAFT = 'DRAFT',
  PENDING_REVIEW = 'PENDING_REVIEW',
  IN_REVISION = 'IN_REVISION',
  REJECTED = 'REJECTED',
  ACCEPTED = 'ACCEPTED',
}

export enum ReviewAssignmentStatus {
  PENDING_ASSIGNMENT = 'PENDING_ASSIGNMENT',
  INVITED = 'INVITED',
  ASSIGNED = 'ASSIGNED',
  CANCELLED = 'CANCELLED',
}

export enum ReviewStatus {
  INVITED = 'INVITED',
  ACCEPTED = 'ACCEPTED',
  SUBMITTED = 'SUBMITTED',
  PUBLISHED = 'PUBLISHED',
  DECLINED = 'DECLINED',
  CANCELLED = 'CANCELLED',
}

export enum AnonymityLevel {
  SINGLE_BLIND = 'SINGLE_BLIND',
  DOUBLE_BLIND = 'DOUBLE_BLIND',
  OPEN_PEER_REVIEW = 'OPEN_PEER_REVIEW',
}

export enum ConflictOfInterestType {
  INSTITUTIONAL = 'INSTITUTIONAL',
  PRIOR_COLLABORATION = 'PRIOR_COLLABORATION',
}

export enum CertificationName {
    PhD = 'PhD',
    MD = 'MD',
    JD = 'JD',
}

export interface Journal {
  id: string;
  journal_name: string;
  status: JournalStatus;
  total_prestige: number;
  prestige_balance: number;
  desk_reject_risk_score: number;
  created_at: string;
  updated_at: string;
}

export interface Manuscript {
  id: string;
  journal_id: string;
  title: string;
  status: ManuscriptStatus;
  submission_date: number;
  is_fast_track_submission: boolean;
  created_at: string;
  updated_at: string;
}

export interface ReviewAssignment {
  id: string;
  manuscript_id: string;
  journal_id: string;
  required_expertise: string;
  status: ReviewAssignmentStatus;
  required_anonymity_level: AnonymityLevel;
  due_date: number;
  revision_cycle: number;
  created_at: string;
  updated_at: string;
}

export interface Certification {
    id: string;
    name: CertificationName;
    granted_date: string;
}

export interface ReviewerProfile {
  id: string;
  journal_id: string;
  full_name: string;
  institution: string;
  expertise_areas: string[];
  certifications: Certification[];
  created_at: string;
  updated_at: string;
}

export interface Review {
  id: string;
  journal_id: string;
  assignment_id: string;
  reviewer_id: string;
  status: ReviewStatus;
  in_extra_revision_cycle: boolean;
  provisional_prestige_cost: number;
  final_prestige_cost: number;
  created_at: string;
  updated_at: string;
}

export interface ConflictOfInterest {
  id: string;
  journal_id: string;
  entity_1_id: string;
  entity_2_id: string;
  conflict_type: ConflictOfInterestType;
  reason?: string | null;
  created_at: string;
}

export interface CreateJournalPayload {
  journal_name: string;
  total_prestige: number;
}

export interface CreateManuscriptPayload {
  title: string;
  submission_date: number;
  is_fast_track_submission?: boolean;
}

export interface UpdateManuscriptPayload {
    status: ManuscriptStatus;
}

export interface CreateReviewAssignmentPayload {
  required_expertise: string;
  required_anonymity_level?: AnonymityLevel;
  due_date: number;
}

export interface ReviewInvitationPayload {
  assignment_id: string;
  reviewer_id: string;
}

export interface CreateReviewerProfilePayload {
  full_name: string;
  institution: string;
  expertise_areas: string[];
}

export interface AddCertificationPayload {
    name: CertificationName;
    granted_date: string;
}

export interface CreateConflictOfInterestPayload {
  entity_1_id: string;
  entity_2_id: string;
  conflict_type: ConflictOfInterestType;
  reason?: string;
}
