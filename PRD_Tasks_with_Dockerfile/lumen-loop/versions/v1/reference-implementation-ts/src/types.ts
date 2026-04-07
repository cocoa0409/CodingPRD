export const ActorTypes = ["Customer", "Support", "Ops", "System"] as const;
export type ActorType = (typeof ActorTypes)[number];

export const ProgramPostures = [
  "PROGRAM_ACTIVE",
  "PROGRAM_GUARDED",
  "PROGRAM_FROZEN",
  "PROGRAM_CLOSED",
] as const;
export type ProgramPosture = (typeof ProgramPostures)[number];

export const CustomerStatuses = ["ACTIVE", "LIMITED", "LOCKED", "CLOSED"] as const;
export type CustomerStatus = (typeof CustomerStatuses)[number];

export const SessionStatuses = ["ACTIVE", "ENDED", "REVOKED"] as const;
export type SessionStatus = (typeof SessionStatuses)[number];

export const BuildLotStatuses = ["AVAILABLE", "QUARANTINED", "CONSUMED"] as const;
export type BuildLotStatus = (typeof BuildLotStatuses)[number];

export const OrderStatuses = [
  "DRAFT",
  "SUBMITTED",
  "ON_HOLD",
  "SHIPPED",
  "DELIVERED",
  "CANCELED",
  "EXPIRED",
  "REFUNDED",
] as const;
export type OrderStatus = (typeof OrderStatuses)[number];

export const PaymentStatuses = [
  "AUTHORIZED",
  "CAPTURED",
  "VOIDED",
  "REFUNDED",
  "DISPUTED",
  "CHARGEBACK_LOST",
] as const;
export type PaymentStatus = (typeof PaymentStatuses)[number];

export const DeviceStatuses = [
  "PROVISIONED",
  "SHIPPED",
  "ACTIVE",
  "QUARANTINED",
  "RETURNED",
  "SCRAPPED",
] as const;
export type DeviceStatus = (typeof DeviceStatuses)[number];

export const CarePlanStatuses = [
  "PENDING_ACTIVATION",
  "ACTIVE",
  "PAUSED",
  "CANCELED",
  "VOIDED",
] as const;
export type CarePlanStatus = (typeof CarePlanStatuses)[number];

export const TradeinStatuses = [
  "DRAFT",
  "SUBMITTED",
  "INBOUND",
  "APPRAISED",
  "CREDITED",
  "REVERSED",
  "EXPIRED",
] as const;
export type TradeinStatus = (typeof TradeinStatuses)[number];

export const ReturnStatuses = [
  "REQUESTED",
  "APPROVED",
  "INBOUND",
  "RECEIVED",
  "COMPLETED",
  "REJECTED",
] as const;
export type ReturnStatus = (typeof ReturnStatuses)[number];

export const ReturnResolutionPreferences = ["REFUND", "REPLACEMENT"] as const;
export type ReturnResolutionPreference = (typeof ReturnResolutionPreferences)[number];

export const ReturnInspectionOutcomes = ["RESTOCK", "REFURB", "SCRAP"] as const;
export type ReturnInspectionOutcome = (typeof ReturnInspectionOutcomes)[number];

export const ClaimStatuses = [
  "OPEN",
  "APPROVED",
  "INBOUND",
  "RECEIVED",
  "ADVANCE_SHIPPED",
  "COMPLETED",
  "CANCELED",
  "EXPIRED",
] as const;
export type ClaimStatus = (typeof ClaimStatuses)[number];

export const ClaimTypes = ["WARRANTY", "CARE_PLAN", "RECALL"] as const;
export type ClaimType = (typeof ClaimTypes)[number];

export const ClaimResolutions = ["REPLACEMENT", "ADVANCE_REPLACEMENT"] as const;
export type ClaimResolution = (typeof ClaimResolutions)[number];

export const AdjustmentStatuses = ["PENDING", "APPLIED", "VOIDED"] as const;
export type AdjustmentStatus = (typeof AdjustmentStatuses)[number];

export const AdjustmentTypes = ["GOODWILL_CREDIT", "WRITE_OFF", "CREDIT_CLAWBACK"] as const;
export type AdjustmentType = (typeof AdjustmentTypes)[number];

export const QualityCampaignTypes = ["SHIP_HOLD", "RECALL"] as const;
export type QualityCampaignType = (typeof QualityCampaignTypes)[number];

export const QualityCampaignStatuses = ["OPEN", "CONTAINED", "RESOLVED", "CLOSED"] as const;
export type QualityCampaignStatus = (typeof QualityCampaignStatuses)[number];

export const AlertStatuses = ["OPEN", "ACKNOWLEDGED", "RESOLVED"] as const;
export type AlertStatus = (typeof AlertStatuses)[number];

export const AlertTypes = [
  "CUSTOMER_LOCKED",
  "PAYMENT_DISPUTED",
  "CHARGEBACK_LOST",
  "TRADEIN_REVERSAL",
  "SUPPLY_SHORTFALL",
  "RECALL_ACTIVE",
  "AFTERCARE_OVERDUE",
] as const;
export type AlertType = (typeof AlertTypes)[number];
