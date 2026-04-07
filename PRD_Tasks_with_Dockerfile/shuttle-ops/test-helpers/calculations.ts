import { PRICING } from './constants';

export function calculateSeatCharge(seatCount: number, seatPriceCents: number = PRICING.POOL_SEAT_PRICE_CENTS): number {
  return seatCount * seatPriceCents;
}

export function calculateWalletAfterCharge(initialBalance: number, seatCount: number): number {
  return initialBalance - calculateSeatCharge(seatCount);
}

export function calculateWalletAfterRefund(currentBalance: number, seatCount: number): number {
  return currentBalance + calculateSeatCharge(seatCount);
}

export function calculateWalletAfterCredit(currentBalance: number, creditCents: number): number {
  return currentBalance + creditCents;
}

export function calculateWalletAfterDebit(currentBalance: number, debitCents: number): number {
  return currentBalance - debitCents;
}

export function calculatePassThenWalletSplit(
  totalSeats: number,
  passSeatsRemaining: number,
  seatPriceCents: number = PRICING.POOL_SEAT_PRICE_CENTS
): {
  passSeatsApplied: number;
  walletSeats: number;
  walletChargeCents: number;
  newPassSeatsRemaining: number;
} {
  const passSeatsApplied = Math.min(totalSeats, passSeatsRemaining);
  const walletSeats = totalSeats - passSeatsApplied;
  const walletChargeCents = walletSeats * seatPriceCents;
  const newPassSeatsRemaining = passSeatsRemaining - passSeatsApplied;

  return {
    passSeatsApplied,
    walletSeats,
    walletChargeCents,
    newPassSeatsRemaining,
  };
}

export function canAffordWalletRide(walletBalance: number, seatCount: number): boolean {
  return walletBalance >= calculateSeatCharge(seatCount);
}

export function canAffordPassThenWalletRide(
  walletBalance: number,
  passSeatsRemaining: number,
  totalSeats: number
): boolean {
  const { walletChargeCents } = calculatePassThenWalletSplit(totalSeats, passSeatsRemaining);
  return walletBalance >= walletChargeCents;
}

export function calculatePassSeatsAfterRide(passSeatsRemaining: number, seatCount: number): number {
  return passSeatsRemaining - seatCount;
}

export function calculatePassSeatsAfterTopUp(passSeatsRemaining: number, addedSeats: number): number {
  return passSeatsRemaining + addedSeats;
}

export function calculateDriverSeatsAfterDispatch(currentSeatsAssigned: number, rideSeatCount: number): number {
  return currentSeatsAssigned + rideSeatCount;
}

export function calculateDriverSeatsAfterRelease(currentSeatsAssigned: number, rideSeatCount: number): number {
  return currentSeatsAssigned - rideSeatCount;
}

export function canDriverAcceptRide(seatCapacity: number, seatsAssigned: number, rideSeatCount: number): boolean {
  return seatsAssigned + rideSeatCount <= seatCapacity;
}

export function calculateDriverRemainingCapacity(seatCapacity: number, seatsAssigned: number): number {
  return seatCapacity - seatsAssigned;
}

export function shouldWaitlist(passSeatsRemaining: number, seatCount: number): boolean {
  return passSeatsRemaining < seatCount;
}
